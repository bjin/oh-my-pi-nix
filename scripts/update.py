#!/usr/bin/env python3

from __future__ import annotations

import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
TMP_ROOT = ROOT / ".tmp"
UPSTREAM_REPO_URL = "https://github.com/can1357/oh-my-pi.git"
UPSTREAM_TAG_GLOB = "v*.*.*"
INPUTS_TO_UPDATE = ("nixpkgs", "rust-overlay")
FAKE_HASH = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


def run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None, capture: bool = True) -> str:
    result = subprocess.run(
        list(args),
        cwd=cwd or ROOT,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else subprocess.STDOUT,
    )
    return result.stdout.strip() if capture and result.stdout is not None else ""


def run_and_capture_output(
    *args: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
 ) -> tuple[int, str]:
    process = subprocess.Popen(
        list(args),
        cwd=cwd or ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output_parts: list[str] = []
    if process.stdout is None:
        raise SystemExit(f"failed to capture output for command: {' '.join(args)}")

    for chunk in process.stdout:
        sys.stdout.write(chunk)
        sys.stdout.flush()
        output_parts.append(chunk)

    return process.wait(), "".join(output_parts)


def require_clean_git_tree() -> None:
    porcelain = run("git", "status", "--porcelain")
    if porcelain:
        raise SystemExit("working tree is not clean; commit or stash changes before running update.py")


def get_latest_tag() -> str:
    output = run(
        "git",
        "ls-remote",
        "--refs",
        "--tags",
        "--sort=-v:refname",
        UPSTREAM_REPO_URL,
        UPSTREAM_TAG_GLOB,
    )
    first_line = output.splitlines()[0]
    ref = first_line.split()[1]
    tag = ref.removeprefix("refs/tags/")
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise SystemExit(f"unexpected upstream tag format: {tag}")
    return tag


def get_current_version() -> str:
    flake_text = (ROOT / "flake.nix").read_text()
    match = re.search(r'^\s*version = "([^"]+)";$', flake_text, re.MULTILINE)
    if match is None:
        raise SystemExit("could not parse current version from flake.nix")
    return match.group(1)


def download_tarball(tag: str, workdir: Path) -> Path:
    tarball_path = workdir / f"{tag}.tar.gz"
    urllib.request.urlretrieve(
        f"https://github.com/can1357/oh-my-pi/archive/refs/tags/{tag}.tar.gz",
        tarball_path,
    )
    return tarball_path


def extract_tarball(tarball_path: Path, workdir: Path) -> Path:
    with tarfile.open(tarball_path, "r:gz") as archive:
        extract_kwargs = {"path": workdir}
        if hasattr(tarfile, "data_filter"):
            extract_kwargs["filter"] = "data"
        archive.extractall(**extract_kwargs)
    candidates = [path for path in workdir.iterdir() if path.is_dir() and path.name.startswith("oh-my-pi-")]
    if len(candidates) != 1:
        raise SystemExit("could not determine extracted source directory")
    return candidates[0]


def get_rust_toolchain_channel(source_dir: Path) -> str:
    content = (source_dir / "rust-toolchain.toml").read_text()
    match = re.search(r'^channel = "([^"]+)"$', content, re.MULTILINE)
    if match is None:
        raise SystemExit("could not parse rust toolchain channel from rust-toolchain.toml")
    return match.group(1)


def compute_src_hash(tarball_path: Path) -> str:
    return run("nix", "hash", "file", "--sri", str(tarball_path))


def update_flake(version: str, rust_toolchain_channel: str, src_hash: str, bun_hash: str, cargo_hash: str) -> None:
    run(
        sys.executable,
        str(SCRIPT_DIR / "update-flake.py"),
        "--version",
        version,
        "--rust-toolchain-channel",
        rust_toolchain_channel,
        "--src-hash",
        src_hash,
        "--bun-hash",
        bun_hash,
        "--cargo-hash",
        cargo_hash,
        capture=False,
    )


def extract_fixed_output_hashes(version: str, build_output: str) -> tuple[str | None, str | None]:
    matches = list(
        re.finditer(
            r"hash mismatch in fixed-output derivation '([^']+)':\n\s*specified:\s*(sha256-[A-Za-z0-9+/=]+)\n\s*got:\s*(sha256-[A-Za-z0-9+/=]+)",
            build_output,
        )
    )
    if not matches:
        raise SystemExit(f"could not extract fixed-output hash from nix output:\n\n{build_output}")

    cargo_hash: str | None = None
    bun_hash: str | None = None
    bun_drv_name = f"oh-my-pi-{version}-bun-deps.drv"
    unexpected_derivations: list[str] = []
    for match in matches:
        drv_name = Path(match.group(1)).name
        drv_label = drv_name.split("-", 1)[1] if "-" in drv_name else drv_name
        got_hash = match.group(3)
        if drv_label == "cargo-deps-vendor-staging.drv":
            cargo_hash = got_hash
            continue
        if drv_label == bun_drv_name:
            bun_hash = got_hash
            continue
        unexpected_derivations.append(drv_name)

    if unexpected_derivations:
        raise SystemExit(
            "encountered unexpected fixed-output derivation mismatch(es): "
            + ", ".join(unexpected_derivations)
            + f"\n\n{build_output}"
        )

    return cargo_hash, bun_hash

def resolve_fixed_output_hashes(version: str, rust_toolchain_channel: str, src_hash: str) -> tuple[str, str]:
    cargo_hash = FAKE_HASH
    bun_hash = FAKE_HASH

    for _ in range(3):
        update_flake(
            version=version,
            rust_toolchain_channel=rust_toolchain_channel,
            src_hash=src_hash,
            bun_hash=bun_hash,
            cargo_hash=cargo_hash,
        )

        returncode, output = run_and_capture_output("nix", "build", ".")
        if returncode == 0:
            return cargo_hash, bun_hash

        next_cargo_hash, next_bun_hash = extract_fixed_output_hashes(version, output)
        updated = False
        if next_cargo_hash is not None and next_cargo_hash != cargo_hash:
            cargo_hash = next_cargo_hash
            updated = True
        if next_bun_hash is not None and next_bun_hash != bun_hash:
            bun_hash = next_bun_hash
            updated = True
        if updated:
            continue

        raise SystemExit(f"nix build failed for an unexpected reason:\n\n{output}")

    raise SystemExit("failed to resolve fixed-output hashes after repeated nix builds")


def verify_build() -> None:
    run("nix", "fmt", "flake.nix", capture=False)
    run("nix", "build", ".", capture=False)
    run("./result/bin/omp", "--version", capture=False)
    run("./result/bin/omp", "grep", "oh-my-pi", ".", capture=False)


def stage_and_commit(tag: str) -> None:
    run("git", "add", "flake.nix", "flake.lock", capture=False)
    run("git", "commit", "-m", f"Update oh-my-pi to {tag}", capture=False)


def main() -> int:
    require_clean_git_tree()
    current_version = get_current_version()
    latest_tag = get_latest_tag()
    latest_version = latest_tag.removeprefix("v")

    if latest_version == current_version:
        print(f"Already up to date at {latest_tag}")
        return 0

    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="oh-my-pi-update-", dir=TMP_ROOT) as temp_dir:
        workdir = Path(temp_dir)
        tarball_path = download_tarball(latest_tag, workdir)
        source_dir = extract_tarball(tarball_path, workdir)
        rust_toolchain_channel = get_rust_toolchain_channel(source_dir)
        src_hash = compute_src_hash(tarball_path)

        print(f"Updating to {latest_tag}")
        print(f"  rust toolchain: {rust_toolchain_channel}")
        print(f"  src hash:       {src_hash}")

        update_flake(
            version=latest_version,
            rust_toolchain_channel=rust_toolchain_channel,
            src_hash=src_hash,
            bun_hash=FAKE_HASH,
            cargo_hash=FAKE_HASH,
        )
        run("nix", "flake", "update", *INPUTS_TO_UPDATE, capture=False)

        cargo_hash, bun_hash = resolve_fixed_output_hashes(
            version=latest_version,
            rust_toolchain_channel=rust_toolchain_channel,
            src_hash=src_hash,
        )

        print(f"  cargo hash:     {cargo_hash}")
        print(f"  bun hash:       {bun_hash}")

    verify_build()
    stage_and_commit(latest_tag)
    print(f"Committed update for {latest_tag}. Review locally, then push when ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

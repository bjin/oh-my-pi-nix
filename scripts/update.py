#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
TMP_ROOT = ROOT / ".tmp"
FLAKE = ROOT / "flake.nix"
LOCK_PATH = ROOT / "flake.lock"
SYSTEM = "x86_64-linux"
INPUT_NAME = "oh-my-pi"
UPSTREAM_REPO_URL = "https://github.com/can1357/oh-my-pi.git"
UPSTREAM_TAG_GLOB = "v*.*.*"
FLAKE_URL_PATTERN = r'^(\s*url = "github:can1357/oh-my-pi/)([0-9a-f]{40})(";)$'


def run(
    *args: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    capture: bool = True,
) -> str:
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


def require_clean_git_tree() -> None:
    porcelain = run("git", "status", "--porcelain")
    if porcelain:
        raise SystemExit(
            "working tree is not clean; commit or stash changes before running update.py"
        )


def resolve_tag_revision(tag: str) -> str:
    output = run(
        "git",
        "ls-remote",
        "--exit-code",
        UPSTREAM_REPO_URL,
        f"refs/tags/{tag}",
        f"refs/tags/{tag}^{{}}",
    )
    refs: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) != 2:
            raise SystemExit(f"unexpected upstream ref line: {line}")
        refs[parts[1]] = parts[0]

    rev = refs.get(f"refs/tags/{tag}^{{}}") or refs.get(f"refs/tags/{tag}")
    if rev is None:
        raise SystemExit(f"upstream tag does not exist: {tag}")
    if not re.fullmatch(r"[0-9a-f]{40}", rev):
        raise SystemExit(f"unexpected upstream revision for {tag}: {rev}")
    return rev


def get_latest_tag() -> tuple[str, str]:
    output = run(
        "git",
        "ls-remote",
        "--refs",
        "--tags",
        "--sort=-v:refname",
        UPSTREAM_REPO_URL,
        UPSTREAM_TAG_GLOB,
    )
    lines = output.splitlines()
    if not lines:
        raise SystemExit("could not find upstream release tags")
    ref = lines[0].split()[1]
    tag = ref.removeprefix("refs/tags/")
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise SystemExit(f"unexpected upstream tag format: {tag}")
    return tag, resolve_tag_revision(tag)


def normalize_tag(raw_version: str) -> str:
    tag = raw_version if raw_version.startswith("v") else f"v{raw_version}"
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise SystemExit(f"unexpected upstream version format: {raw_version}")
    return tag


def resolve_target_tag(raw_version: str | None) -> tuple[str, str, str]:
    if raw_version:
        tag = normalize_tag(raw_version)
        rev = resolve_tag_revision(tag)
    else:
        tag, rev = get_latest_tag()
    return tag, tag.removeprefix("v"), rev


def read_flake_rev() -> str:
    match = re.search(FLAKE_URL_PATTERN, FLAKE.read_text(), re.MULTILINE)
    if match is None:
        raise SystemExit("could not parse the oh-my-pi input commit from flake.nix")
    return match.group(2)


def write_flake_rev(rev: str) -> None:
    content, count = re.subn(
        FLAKE_URL_PATTERN,
        lambda match: f"{match.group(1)}{rev}{match.group(3)}",
        FLAKE.read_text(),
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise SystemExit("could not rewrite the oh-my-pi input commit in flake.nix")
    FLAKE.write_text(content)


def read_locked_rev() -> str:
    lock = json.loads(LOCK_PATH.read_text())
    # Node names are not input names: a transitive input of `oh-my-pi-upstream`
    # can take the plain name and push this repository's own node to `<name>_2`.
    node = lock["nodes"]["root"]["inputs"][INPUT_NAME]
    return lock["nodes"][node]["locked"]["rev"]


def read_package_version() -> str:
    # The derivation takes its version from the pinned source tree, so this also
    # proves the tag points at the release it claims to be.
    return run("nix", "eval", "--raw", f".#packages.{SYSTEM}.oh-my-pi.version")


def run_omp_isolated(*args: str, extra_env: dict[str, str] | None = None) -> str:
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="oh-my-pi-smoke-", dir=TMP_ROOT
    ) as temp_dir:
        temp_path = Path(temp_dir)
        home = temp_path / "home"
        xdg_data_home = temp_path / "xdg-data"
        home.mkdir()
        (xdg_data_home / "omp").mkdir(parents=True)
        return run(
            "./result/bin/omp",
            *args,
            env={
                **os.environ,
                **(extra_env or {}),
                "HOME": str(home),
                "XDG_DATA_HOME": str(xdg_data_home),
            },
        )


def verify_haskell_crash_regression() -> None:
    output = run_omp_isolated("read", str(ROOT / "Crash.hs"))
    if not output:
        raise SystemExit("Haskell crash regression produced no output")


def verify_embedded_bun_runtime() -> None:
    # The standalone binary is written into a pristine release of the Bun that
    # upstream's engines.bun asks for. Without that template the CLI still
    # starts, but every `Bun.Image` caller (image resize, PNG conversion, kitty
    # rendering) silently degrades.
    output = run_omp_isolated(
        "-e",
        "console.log(`${Bun.version} ${typeof Bun.Image}`)",
        extra_env={"BUN_BE_BUN": "1"},
    )
    version, _, image_kind = output.partition(" ")
    if image_kind != "function":
        raise SystemExit(f"embedded Bun {version} lacks Bun.Image")


def verify_smoke_test() -> None:
    output = run_omp_isolated("--smoke-test")
    if output != "smoke-test: ok":
        raise SystemExit(f"unexpected smoke test output: {output!r}")
    verify_haskell_crash_regression()
    verify_embedded_bun_runtime()


def verify_no_embedded_native_addons() -> None:
    omp_binary = ROOT / "result/lib/omp/omp"
    embedded_markers = (
        b"embedded-addons.linux-x64.tar.gz",
        b"pi_natives.linux-x64-baseline.node",
        b"pi_natives.linux-x64-modern.node",
    )
    binary = omp_binary.read_bytes()
    found_markers = [marker.decode() for marker in embedded_markers if marker in binary]
    if found_markers:
        formatted = "\n".join(f"  {marker}" for marker in found_markers)
        raise SystemExit(
            f"omp binary embeds native addon metadata; expected loose .node files:\n{formatted}"
        )


def verify_build() -> None:
    run("nix", "fmt", "flake.nix", capture=False)
    run("nix", "build", ".", capture=False)
    verify_smoke_test()
    verify_no_embedded_native_addons()


def commit_message(tag: str, version: str, previous_version: str, rev: str) -> str:
    if version == previous_version:
        return f"Update oh-my-pi {tag} source revision to {rev[:12]}"
    return f"Update oh-my-pi to {tag}"


def stage_and_commit(message: str) -> None:
    run("git", "add", "flake.nix", "flake.lock", capture=False)
    run("git", "commit", "-m", message, capture=False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update this flake to an upstream oh-my-pi release"
    )
    parser.add_argument(
        "--version",
        help="target upstream version, for example 17.3.0 or v17.3.0; defaults to the latest tag",
    )
    args = parser.parse_args()

    require_clean_git_tree()

    previous_rev = read_locked_rev()
    if read_flake_rev() != previous_rev:
        raise SystemExit(
            "flake.nix and flake.lock disagree on the pinned oh-my-pi commit; "
            "run `nix flake update oh-my-pi` and commit the result first"
        )
    previous_version = read_package_version()
    tag, version, rev = resolve_target_tag(args.version)

    if rev == previous_rev:
        print(f"Already up to date at {tag} ({rev})")
        return 0

    if version == previous_version:
        print(f"Upstream tag {tag} moved from {previous_rev} to {rev}")
    else:
        print(f"Updating from {previous_version} to {version} ({rev})")

    write_flake_rev(rev)
    run("nix", "flake", "update", INPUT_NAME, capture=False)

    locked_rev = read_locked_rev()
    if locked_rev != rev:
        raise SystemExit(
            f"locked oh-my-pi commit is {locked_rev}, expected {rev}"
        )

    package_version = read_package_version()
    if package_version != version:
        raise SystemExit(
            f"upstream tag {tag} builds version {package_version}, not {version}"
        )

    verify_build()
    stage_and_commit(commit_message(tag, version, previous_version, rev))
    print(f"Committed update for {tag}. Review locally, then push when ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

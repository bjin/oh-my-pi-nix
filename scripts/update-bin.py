#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
TMP_ROOT = ROOT / ".tmp"
BIN_HASHES = ROOT / "bin-hashes.json"
UPSTREAM_API = "https://api.github.com/repos/can1357/oh-my-pi"
FLAKE = ROOT / "flake.nix"
LOCK_PATH = ROOT / "flake.lock"
SYSTEM = "x86_64-linux"
UPSTREAM_INPUT = "oh-my-pi-upstream"
UPSTREAM_REPO_URL = "https://github.com/can1357/oh-my-pi.git"
# Whole-line, and scoped to the input attribute: the `oh-my-pi` source input
# that update.py rewrites carries the same URL prefix.
FLAKE_URL_PATTERN = (
    r'^(\s*oh-my-pi-upstream\.url = "github:can1357/oh-my-pi/)([0-9a-f]{40})(";)$'
)
ASSET_BY_SYSTEM = {
    "x86_64-linux": "omp-linux-x64",
}


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


def normalize_tag(raw_version: str) -> str:
    tag = raw_version if raw_version.startswith("v") else f"v{raw_version}"
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise SystemExit(f"unexpected upstream version format: {raw_version}")
    return tag


def resolve_tag_revision(tag: str) -> str:
    # The release payload names the tag, not the commit under it, and a tag ref
    # in the flake input would be re-resolved through Nix's cached GitHub ref
    # lookup, so ask the remote (`^{}` peels an annotated tag).
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


def read_flake_rev() -> str:
    match = re.search(FLAKE_URL_PATTERN, FLAKE.read_text(), re.MULTILINE)
    if match is None:
        raise SystemExit(
            f"could not parse the {UPSTREAM_INPUT} input commit from flake.nix"
        )
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
        raise SystemExit(
            f"could not rewrite the {UPSTREAM_INPUT} input commit in flake.nix"
        )
    FLAKE.write_text(content)


def read_locked_rev() -> str:
    lock = json.loads(LOCK_PATH.read_text())
    node = lock["nodes"]["root"]["inputs"][UPSTREAM_INPUT]
    return lock["nodes"][node]["locked"]["rev"]


def request_json(url: str) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "oh-my-pi-nix-update-bin",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise SystemExit(f"unexpected GitHub API response from {url}")
    return payload


def get_release(tag: str | None) -> dict[str, Any]:
    if tag is None:
        return request_json(f"{UPSTREAM_API}/releases/latest")
    return request_json(f"{UPSTREAM_API}/releases/tags/{tag}")


def parse_release_version(release: dict[str, Any]) -> str:
    tag_name = release.get("tag_name")
    if not isinstance(tag_name, str):
        raise SystemExit("release is missing tag_name")
    tag = normalize_tag(tag_name)
    return tag.removeprefix("v")


def digest_to_sri(digest: str) -> str:
    prefix = "sha256:"
    if not digest.startswith(prefix):
        raise ValueError(f"unsupported asset digest: {digest}")
    hex_digest = digest.removeprefix(prefix)
    if not re.fullmatch(r"[0-9a-fA-F]{64}", hex_digest):
        raise ValueError(f"unsupported asset digest: {digest}")
    return "sha256-" + base64.b64encode(bytes.fromhex(hex_digest)).decode("ascii")


def hash_asset_by_download(asset: dict[str, Any], workdir: Path) -> str:
    name = asset.get("name")
    url = asset.get("browser_download_url")
    if not isinstance(name, str) or not isinstance(url, str):
        raise SystemExit("release asset is missing name or browser_download_url")

    destination = workdir / name
    urllib.request.urlretrieve(url, destination)
    return run("nix", "hash", "file", "--sri", str(destination))


def asset_hash(asset: dict[str, Any], workdir: Path) -> str:
    digest = asset.get("digest")
    if isinstance(digest, str) and digest:
        try:
            return digest_to_sri(digest)
        except ValueError as exc:
            print(f"{exc}; downloading asset to compute hash", file=sys.stderr)
    return hash_asset_by_download(asset, workdir)


def release_assets_by_name(release: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise SystemExit("release is missing assets")

    result: dict[str, dict[str, Any]] = {}
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = asset.get("name")
        if isinstance(name, str):
            result[name] = asset
    return result


def compute_hashes(release: dict[str, Any], workdir: Path) -> dict[str, str]:
    assets = release_assets_by_name(release)
    hashes: dict[str, str] = {}
    missing_assets: list[str] = []

    for system, asset_name in ASSET_BY_SYSTEM.items():
        asset = assets.get(asset_name)
        if asset is None:
            missing_assets.append(asset_name)
            continue
        hashes[system] = asset_hash(asset, workdir)

    if missing_assets:
        formatted = ", ".join(sorted(missing_assets))
        raise SystemExit(f"release is missing required asset(s): {formatted}")
    return hashes


def read_bin_hashes() -> dict[str, Any]:
    data = json.loads(BIN_HASHES.read_text())
    if not isinstance(data, dict):
        raise SystemExit("bin-hashes.json is not a JSON object")
    version = data.get("version")
    hashes = data.get("hashes")
    if not isinstance(version, str) or not version:
        raise SystemExit("bin-hashes.json is missing version")
    if not isinstance(hashes, dict):
        raise SystemExit("bin-hashes.json is missing hashes")
    return data


def write_bin_hashes(*, version: str, hashes: dict[str, str]) -> None:
    BIN_HASHES.write_text(
        json.dumps(
            {
                "version": version,
                "hashes": hashes,
            },
            indent=2,
        )
        + "\n"
    )


def require_clean_git_tree() -> None:
    porcelain = run("git", "status", "--porcelain")
    if porcelain:
        raise SystemExit(
            "working tree is not clean; commit or stash changes before running update-bin.py"
        )


def run_omp_bin_isolated(*args: str) -> str:
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="oh-my-pi-bin-smoke-", dir=TMP_ROOT
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
                "HOME": str(home),
                "XDG_DATA_HOME": str(xdg_data_home),
            },
        )


def verify_smoke_test() -> None:
    output = run_omp_bin_isolated("--smoke-test")
    if output != "smoke-test: ok":
        raise SystemExit(f"unexpected smoke test output: {output!r}")


def verify_build() -> None:
    run("nix", "build", ".#oh-my-pi-bin", capture=False)
    verify_smoke_test()


def eval_store_path(flake_ref: str, attribute: str) -> str:
    # Not `run`: a failed evaluation carries the flake's own message — including
    # the throw for a pin that disagrees with bin-hashes.json — and folding that
    # into a CalledProcessError would drop it from the updater's log.
    result = subprocess.run(
        ["nix", "eval", "--raw", f"{flake_ref}#packages.{SYSTEM}.{attribute}.outPath"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise SystemExit(
            result.stderr.strip() or f"could not evaluate {flake_ref}#{attribute}"
        )
    return result.stdout.strip()


def verify_upstream_pin(tag: str) -> None:
    # `#upstream` only re-exports upstream's package, so it has to resolve to
    # the very store path the release tag builds — the one upstream.yml pushes
    # to Cachix. Evaluating it also forces the flake's assertion that the
    # pinned tree is the release bin-hashes.json names. Eval only: the build
    # itself belongs to upstream.yml, which caches it once per release.
    ours = eval_store_path(".", "upstream")
    theirs = eval_store_path(f"github:can1357/oh-my-pi/{tag}", "default")
    if ours != theirs:
        raise SystemExit(f"#upstream resolves to {ours}, but {tag} builds {theirs}")


def stage_and_commit(message: str) -> None:
    run("git", "add", "bin-hashes.json", "flake.nix", "flake.lock", capture=False)
    run("git", "commit", "-m", message, capture=False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update the oh-my-pi-bin package to an upstream binary release"
    )
    parser.add_argument(
        "--version",
        help="target upstream binary release, for example 17.3.0 or v17.3.0; defaults to the latest release. 17.3.0 and later only: earlier tags carry no flake to pin for #upstream",
    )
    args = parser.parse_args()

    require_clean_git_tree()
    current = read_bin_hashes()
    requested_tag = normalize_tag(args.version) if args.version else None
    release = get_release(requested_tag)
    latest_version = parse_release_version(release)
    latest_tag = f"v{latest_version}"

    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="oh-my-pi-bin-update-", dir=TMP_ROOT) as temp_dir:
        hashes = compute_hashes(release, Path(temp_dir))

    # `#upstream` is upstream's own flake at this release, so the pin and
    # bin-hashes.json move in one commit; the flake refuses to evaluate when
    # they disagree.
    rev = resolve_tag_revision(latest_tag)
    bin_current = latest_version == current["version"] and hashes == current["hashes"]
    pin_current = read_flake_rev() == rev and read_locked_rev() == rev

    if bin_current and pin_current:
        print(f"oh-my-pi-bin is already up to date at {latest_tag}")
        return 0

    message = (
        f"Repin {UPSTREAM_INPUT} to {latest_tag}"
        if bin_current
        else f"Update oh-my-pi-bin to {latest_tag}"
    )
    print(message)

    if not bin_current:
        for system, hash_value in sorted(hashes.items()):
            print(f"  {system}: {hash_value}")
        write_bin_hashes(version=latest_version, hashes=hashes)

    if not pin_current:
        write_flake_rev(rev)
        run("nix", "flake", "update", UPSTREAM_INPUT, capture=False)
        locked_rev = read_locked_rev()
        if locked_rev != rev:
            raise SystemExit(
                f"locked {UPSTREAM_INPUT} commit is {locked_rev}, expected {rev}"
            )

    verify_upstream_pin(latest_tag)
    verify_build()
    stage_and_commit(message)
    print(f"Committed: {message}. Review locally, then push when ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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


def stage_and_commit(tag: str) -> None:
    run("git", "add", "bin-hashes.json", capture=False)
    run("git", "commit", "-m", f"Update oh-my-pi-bin to {tag}", capture=False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update the oh-my-pi-bin package to an upstream binary release"
    )
    parser.add_argument(
        "--version",
        help="target upstream binary release, for example 15.1.8 or v15.1.8; defaults to the latest release",
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

    if latest_version == current["version"] and hashes == current["hashes"]:
        print(f"oh-my-pi-bin is already up to date at {latest_tag}")
        return 0


    print(f"Updating oh-my-pi-bin to {latest_tag}")
    for system, hash_value in sorted(hashes.items()):
        print(f"  {system}: {hash_value}")

    write_bin_hashes(version=latest_version, hashes=hashes)
    verify_build()
    stage_and_commit(latest_tag)
    print(f"Committed oh-my-pi-bin update for {latest_tag}. Review locally, then push when ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

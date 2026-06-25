#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TMP_ROOT = ROOT / ".tmp"
LOCK_PATH = ROOT / "flake.lock"
INPUTS_TO_UPDATE = ("nixpkgs", "rust-overlay")
PACKAGES_TO_VERIFY = ("oh-my-pi", "oh-my-pi-bin")


def run(
    *args: str,
    cwd: Path | None = None,
    capture: bool = True,
    env: dict[str, str] | None = None,
) -> str:
    result = subprocess.run(
        list(args),
        cwd=cwd or ROOT,
        check=True,
        text=True,
        capture_output=capture,
        env=env,
    )
    return result.stdout.strip() if capture else ""


def require_clean_git_tree() -> None:
    porcelain = run("git", "status", "--porcelain")
    if porcelain:
        raise SystemExit(
            "working tree is not clean; commit or stash changes before running update-deps.py"
        )


def read_locked_revs() -> dict[str, str]:
    lock = json.loads(LOCK_PATH.read_text())
    return {
        input_name: lock["nodes"][input_name]["locked"]["rev"]
        for input_name in INPUTS_TO_UPDATE
    }


def stage_and_commit() -> None:
    run("git", "add", "flake.lock", capture=False)
    run("git", "commit", "-m", "Update flake inputs", capture=False)


def run_omp_isolated(omp_binary: Path, *args: str) -> None:
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="oh-my-pi-deps-smoke-", dir=TMP_ROOT
    ) as temp_dir:
        temp_path = Path(temp_dir)
        home = temp_path / "home"
        xdg_data_home = temp_path / "xdg-data"
        home.mkdir()
        (xdg_data_home / "omp").mkdir(parents=True)
        run(
            str(omp_binary),
            *args,
            env={
                **os.environ,
                "HOME": str(home),
                "XDG_DATA_HOME": str(xdg_data_home),
            },
            capture=False,
        )


def verify_package(package: str) -> None:
    out_link = TMP_ROOT / f"update-deps-{package}-result"
    run(
        "nix",
        "build",
        f".#{package}",
        "--out-link",
        str(out_link),
        capture=False,
    )
    omp_binary = out_link / "bin" / "omp"
    run_omp_isolated(omp_binary, "--version")
    run_omp_isolated(omp_binary, "grep", "oh-my-pi", ".")


def verify_builds() -> None:
    for package in PACKAGES_TO_VERIFY:
        verify_package(package)


def main() -> int:
    require_clean_git_tree()
    before = read_locked_revs()

    run("nix", "flake", "update", *INPUTS_TO_UPDATE, capture=False)

    after = read_locked_revs()
    if after == before:
        print("flake inputs are already up to date")
        return 0

    for input_name in INPUTS_TO_UPDATE:
        print(f"{input_name}: {before[input_name]} -> {after[input_name]}")

    verify_builds()
    stage_and_commit()
    print("Committed flake input update. Review locally, then push when ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LOCK_PATH = ROOT / "flake.lock"
INPUTS_TO_UPDATE = ("nixpkgs", "rust-overlay")


def run(*args: str, cwd: Path | None = None, capture: bool = True) -> str:
    result = subprocess.run(
        list(args),
        cwd=cwd or ROOT,
        check=True,
        text=True,
        capture_output=capture,
    )
    return result.stdout.strip() if capture else ""


def require_clean_git_tree() -> None:
    porcelain = run("git", "status", "--porcelain")
    if porcelain:
        raise SystemExit("working tree is not clean; commit or stash changes before running update-deps.py")


def read_locked_revs() -> dict[str, str]:
    lock = json.loads(LOCK_PATH.read_text())
    return {
        input_name: lock["nodes"][input_name]["locked"]["rev"]
        for input_name in INPUTS_TO_UPDATE
    }


def stage_and_commit() -> None:
    run("git", "add", "flake.lock", capture=False)
    run("git", "commit", "-m", "Update flake inputs", capture=False)


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

    run("nix", "build", ".", capture=False)
    stage_and_commit()
    print("Committed flake input update. Review locally, then push when ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

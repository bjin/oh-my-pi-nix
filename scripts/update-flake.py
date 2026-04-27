#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections.abc import Callable

ROOT = pathlib.Path(__file__).resolve().parent.parent
FLAKE = ROOT / "flake.nix"
HASHES = ROOT / "hashes.json"


def replace_once(text: str, pattern: str, replacement: str | Callable[[re.Match[str]], str]) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE | re.DOTALL)
    if count != 1:
        raise RuntimeError(f"expected exactly one match for pattern: {pattern}")
    return updated


def replace_captured_value(text: str, pattern: str, value: str) -> str:
    return replace_once(text, pattern, lambda match: f"{match.group(1)}{value}{match.group(2)}")


def update_flake_text(
    text: str,
    *,
    rust_toolchain_channel: str,
) -> str:
    return replace_captured_value(
        text,
        r'^(\s*rustToolchainChannel = ")[^"]+(";)$',
        rust_toolchain_channel,
    )


def write_hashes(*, version: str, src_hash: str, bun_hash: str, cargo_hash: str) -> None:
    HASHES.write_text(
        json.dumps(
            {
                "version": version,
                "srcHash": src_hash,
                "bunHash": bun_hash,
                "cargoHash": cargo_hash,
            },
            indent=2,
        )
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Update versioned values in flake.nix and hashes.json")
    parser.add_argument("--version", required=True)
    parser.add_argument("--rust-toolchain-channel", required=True)
    parser.add_argument("--src-hash", required=True)
    parser.add_argument("--bun-hash", required=True)
    parser.add_argument("--cargo-hash", required=True)
    args = parser.parse_args()

    FLAKE.write_text(
        update_flake_text(
            FLAKE.read_text(),
            rust_toolchain_channel=args.rust_toolchain_channel,
        )
    )
    write_hashes(
        version=args.version,
        src_hash=args.src_hash,
        bun_hash=args.bun_hash,
        cargo_hash=args.cargo_hash,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise

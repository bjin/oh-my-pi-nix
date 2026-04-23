#!/usr/bin/env python3

from __future__ import annotations

import argparse
import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parent.parent
FLAKE = ROOT / "flake.nix"


def replace_once(text: str, pattern: str, replacement: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE | re.DOTALL)
    if count != 1:
        raise RuntimeError(f"expected exactly one match for pattern: {pattern}")
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="Update versioned values in flake.nix")
    parser.add_argument("--version", required=True)
    parser.add_argument("--rust-toolchain-channel", required=True)
    parser.add_argument("--src-hash", required=True)
    parser.add_argument("--bun-hash", required=True)
    parser.add_argument("--cargo-hash", required=True)
    args = parser.parse_args()

    text = FLAKE.read_text()

    text = replace_once(
        text,
        r'^(\s*version = ")[^"]+(";)$',
        rf'\1{args.version}\2',
    )
    text = replace_once(
        text,
        r'^(\s*rustToolchainChannel = ")[^"]+(";)$',
        rf'\1{args.rust_toolchain_channel}\2',
    )
    text = replace_once(
        text,
        r'(src = pkgs\.fetchurl \{\s*url = "[^"]+";\s*hash = ")[^"]+(";\s*\})',
        rf'\1{args.src_hash}\2',
    )
    text = replace_once(
        text,
        r'^(\s*outputHash = ")[^"]+(";)$',
        rf'\1{args.bun_hash}\2',
    )
    text = replace_once(
        text,
        r'(cargoDeps = rustPlatform\.fetchCargoVendor \{\s*inherit src;\s*sourceRoot = "\$\{pname\}-\$\{version\}";\s*hash = ")[^"]+(";\s*\})',
        rf'\1{args.cargo_hash}\2',
    )

    FLAKE.write_text(text)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise

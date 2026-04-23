# oh-my-pi-nix

Nix flake packaging for [oh-my-pi](https://github.com/can1357/oh-my-pi).

## What is this repo?

This repository contains a Nix flake that builds `oh-my-pi` from the upstream source release tarball instead of using the prebuilt binaries.

Current properties of this flake:

- packages upstream `oh-my-pi` release `v14.1.4`
- uses the pinned nightly Rust toolchain required by upstream (`nightly-2026-03-27`)
- builds the native addons from source
- builds the compiled `omp` CLI from source with Bun
- currently targets `x86_64-linux`

The package output installs:

- `omp`
- `pi_natives.linux-x64-baseline.node`
- `pi_natives.linux-x64-modern.node`

## Build locally

Build the package from this repository checkout:

```bash
nix build .
```

Run the built binary without installing it:

```bash
./result/bin/omp --version
```

## Install with `nix`

Install directly from this GitHub repository into your user profile:

```bash
nix profile install github:bjin/oh-my-pi-nix#default
```

After installation, `omp` will be available from your profile.

You can also build directly from GitHub without cloning the repo first:

```bash
nix build github:bjin/oh-my-pi-nix#default
```

Or run it directly:

```bash
nix run github:bjin/oh-my-pi-nix#default -- --version
```

## Updating to a newer upstream tag

Use the local updater to move this flake to the newest upstream `v*.*.*` tag:

```bash
python3 scripts/update.py
```

`scripts/update.py` will:

- query the newest upstream tag with `git ls-remote`
- fetch the upstream source tarball into the repo-local temporary directory ignored by `.gitignore` (`.tmp/`)
- read the upstream Rust toolchain channel from `rust-toolchain.toml`
- update `flake.nix` via `scripts/update_flake.py` and refresh `flake.lock` for `rust-overlay`
- let repeated `nix build .` runs discover the Bun and Cargo fixed-output hashes
- run `nix build .`
- verify `./result/bin/omp --version`
- verify `./result/bin/omp grep oh-my-pi .` exits successfully
- stage and commit the flake update locally

It does not push to GitHub. Review the commit, then push it yourself when ready.
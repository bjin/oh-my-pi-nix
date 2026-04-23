# oh-my-pi-nix

Nix flake packaging for [oh-my-pi](https://github.com/can1357/oh-my-pi).

## What is this repo?

This repository contains a Nix flake that builds `oh-my-pi` from the upstream source release tarball instead of using the prebuilt binaries.

Current properties of this flake:

- packages upstream `oh-my-pi` release `v14.1.4`
- uses the pinned nightly Rust toolchain required by upstream (`nightly-2026-03-27`)
- builds the native addons from source
- builds the compiled `omp` CLI from source with Bun
- currently supports `x86_64-linux` only

The package output installs:

- `omp`
- `pi_natives.linux-x64-baseline.node`
- `pi_natives.linux-x64-modern.node`

This flake currently supports `x86_64-linux` only. Patches and pull requests to extend it to additional platforms are welcome.

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

Install from the public Cachix binary cache to avoid a local build when a matching package is available:

```bash
nix shell nixpkgs#cachix -c cachix use oh-my-pi
nix profile add github:bjin/oh-my-pi-nix#oh-my-pi
```

You can also install directly from the GitHub flake into your user profile:

```bash
nix profile add github:bjin/oh-my-pi-nix#oh-my-pi
```

After installation, `omp` will be available from your profile.

You can also build directly from GitHub without cloning the repo first:

```bash
nix build github:bjin/oh-my-pi-nix#oh-my-pi
```

Or run it directly:

```bash
nix run github:bjin/oh-my-pi-nix#oh-my-pi -- --version
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

## Refreshing locked flake inputs

To update the locked `nixpkgs` and `rust-overlay` revisions manually, run:

```bash
nix flake update nixpkgs rust-overlay
```

`nix flake lock` only refreshes missing lock entries. To update existing locked inputs, use `nix flake update`.

If you want the repository helper to do that update and verify it still builds, run:

```bash
python3 scripts/update-deps.py
```

`scripts/update-deps.py` will:

- update the locked `nixpkgs` and `rust-overlay` revisions in `flake.lock`
- run `nix build .` to verify the refreshed lock file still builds
- stage `flake.lock` and commit the lock refresh locally

It does not push to GitHub. Review the commit, then push it yourself when ready.
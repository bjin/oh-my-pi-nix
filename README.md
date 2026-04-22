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

## Update notes

This flake is pinned with `flake.lock`, and the packaged `oh-my-pi` version is declared in `flake.nix`.
If upstream releases a newer version, update the version and source hash in `flake.nix`, then refresh any build hashes as needed.

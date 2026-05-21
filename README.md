# oh-my-pi-nix

Nix flake for installing and building [oh-my-pi](https://github.com/can1357/oh-my-pi) from source, plus an independently versioned upstream binary package.

## Install

This flake currently supports `x86_64-linux` only. Patches and pull requests to extend it to additional platforms are welcome.

Fastest path, using the public Cachix cache:

```bash
nix shell nixpkgs#cachix -c cachix use oh-my-pi
nix profile add github:bjin/oh-my-pi-nix#oh-my-pi
```

Directly from GitHub, without configuring Cachix first:

```bash
nix profile add github:bjin/oh-my-pi-nix#oh-my-pi
```

Install the upstream binary package instead:

```bash
nix profile add github:bjin/oh-my-pi-nix#oh-my-pi-bin
```

After installation, `omp` will be available from your profile.

## Run without installing

```bash
nix run github:bjin/oh-my-pi-nix#oh-my-pi -- --version
```

## Build locally

```bash
nix build .
./result/bin/omp --version
```

## For maintainers

Bump the source-built `oh-my-pi` package to the latest upstream release:

```bash
python3 scripts/update.py
```

This updates the packaged upstream release, refreshes the hashes and lock data needed for the build, verifies with `nix build .`, and creates a local commit.

Bump the upstream binary `oh-my-pi-bin` package to the latest release:

```bash
python3 scripts/update-bin.py
```

This updates only `bin-hashes.json`, verifies with `nix build .#oh-my-pi-bin`, and creates a local commit. The source-built and binary packages are intentionally versioned and updated independently.

Refresh locked flake inputs:

```bash
python3 scripts/update-deps.py
```

This updates the locked flake inputs, verifies with `nix build .`, and creates a local commit.
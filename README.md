# oh-my-pi-nix

Nix flake for installing and building [oh-my-pi](https://github.com/can1357/oh-my-pi) from source.

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

Bump to the latest upstream release:

```bash
python3 scripts/update.py
```

This updates the packaged upstream release, refreshes the hashes and lock data needed for the build, verifies with `nix build .`, and creates a local commit.

Refresh locked flake inputs:

```bash
python3 scripts/update-deps.py
```

This updates the locked flake inputs, verifies with `nix build .`, and creates a local commit.
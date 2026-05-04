{
  description = "Build oh-my-pi from the upstream source release";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    rust-overlay = {
      url = "github:oxalica/rust-overlay";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      rust-overlay,
    }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;
        overlays = [ rust-overlay.overlays.default ];
      };
      lib = pkgs.lib;

      pname = "oh-my-pi";
      versionData = builtins.fromJSON (builtins.readFile ./hashes.json);
      version = versionData.version;
      rustToolchainChannel = "nightly-2026-04-29";
      rustTarget = "x86_64-unknown-linux-gnu";
      runtimeLibraryPath = lib.makeLibraryPath [
        pkgs.stdenv.cc.cc.lib
        pkgs.zlib
      ];

      src = pkgs.fetchurl {
        url = "https://github.com/can1357/oh-my-pi/archive/refs/tags/v${version}.tar.gz";
        hash = versionData.srcHash;
      };

      toolchainWithTarget =
        let
          nightlyDateMatch = builtins.match "nightly-(.+)" rustToolchainChannel;
          stableVersionMatch = builtins.match "[0-9]+\\.[0-9]+\\.[0-9]+" rustToolchainChannel;
          baseToolchain =
            if nightlyDateMatch != null then
              pkgs.rust-bin.nightly."${builtins.head nightlyDateMatch}".minimal
            else if rustToolchainChannel == "nightly" then
              pkgs.rust-bin.selectLatestNightlyWith (toolchain: toolchain.minimal)
            else if rustToolchainChannel == "stable" then
              pkgs.rust-bin.stable.latest.minimal
            else if rustToolchainChannel == "beta" then
              pkgs.rust-bin.beta.latest.minimal
            else if stableVersionMatch != null then
              pkgs.rust-bin.stable."${rustToolchainChannel}".minimal
            else
              throw "Unsupported rustToolchainChannel: ${rustToolchainChannel}";
        in
        baseToolchain.override {
          targets = [ rustTarget ];
        };

      rustPlatform = pkgs.makeRustPlatform {
        cargo = toolchainWithTarget;
        rustc = toolchainWithTarget;
      };

      bunDeps = pkgs.stdenvNoCC.mkDerivation {
        name = "${pname}-${version}-bun-deps";
        inherit src;
        sourceRoot = "${pname}-${version}";

        nativeBuildInputs = [ pkgs.bun ];
        strictDeps = true;
        dontConfigure = true;
        dontFixup = true;
        impureEnvVars = lib.fetchers.proxyImpureEnvVars;

        buildPhase = ''
          runHook preBuild

          export HOME="$TMPDIR/home"
          export XDG_CACHE_HOME="$TMPDIR/xdg-cache"
          export BUN_INSTALL_CACHE_DIR="$TMPDIR/bun-install-cache"
          mkdir -p "$HOME" "$XDG_CACHE_HOME" "$BUN_INSTALL_CACHE_DIR"

          bun install --frozen-lockfile --linker=hoisted --backend=copyfile

          runHook postBuild
        '';

        installPhase = ''
          runHook preInstall

          mkdir -p "$out"
          cp -a node_modules "$out/node_modules"

          runHook postInstall
        '';

        outputHashMode = "recursive";
        outputHash = versionData.bunHash;
      };

      cargoDeps = rustPlatform.fetchCargoVendor {
        inherit src;
        sourceRoot = "${pname}-${version}";
        hash = versionData.cargoHash;
      };

      package = pkgs.stdenv.mkDerivation {
        inherit
          pname
          version
          src
          cargoDeps
          ;
        sourceRoot = "${pname}-${version}";

        nativeBuildInputs = [
          pkgs.autoPatchelfHook
          pkgs.bun
          pkgs.makeWrapper
          pkgs.pkg-config
          toolchainWithTarget
          rustPlatform.cargoSetupHook
        ];

        buildInputs = [
          pkgs.stdenv.cc.cc.lib
          pkgs.zlib
        ];
        strictDeps = true;
        dontStrip = true;

        buildPhase = ''
          runHook preBuild

          export HOME="$TMPDIR/home"
          export XDG_CACHE_HOME="$TMPDIR/xdg-cache"
          export BUN_INSTALL_CACHE_DIR="$TMPDIR/bun-install-cache"
          export CARGO_TARGET_DIR="$TMPDIR/cargo-target"
          mkdir -p "$HOME" "$XDG_CACHE_HOME" "$BUN_INSTALL_CACHE_DIR" "$CARGO_TARGET_DIR"
          export LD_LIBRARY_PATH="${lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib ]}"
          export LIBCLANG_PATH="${pkgs.libclang.lib}/lib"

          cp -a ${bunDeps}/node_modules ./node_modules
          chmod -R u+w ./node_modules
          substituteInPlace node_modules/@napi-rs/cli/dist/cli.js \
            --replace-fail '#!/usr/bin/env node' '#!${pkgs.bun}/bin/bun'

          CI=1 TARGET_VARIANTS="baseline modern" bun run ci:build:native
          bun --cwd=packages/coding-agent run generate-docs-index
          bun --cwd=packages/coding-agent run build

          runHook postBuild
        '';

        installPhase = ''
          runHook preInstall

          install -Dm755 packages/coding-agent/dist/omp "$out/lib/omp/omp"
          makeWrapper "$out/lib/omp/omp" "$out/bin/omp" \
            --set PI_SKIP_VERSION_CHECK 1 \
            --prefix LD_LIBRARY_PATH : "${runtimeLibraryPath}"
          install -Dm644 LICENSE "$out/share/licenses/${pname}/LICENSE"

          runHook postInstall
        '';

        doInstallCheck = true;
        installCheckPhase = ''
          runHook preInstallCheck

          export HOME="$TMPDIR/check-home"
          export XDG_DATA_HOME="$TMPDIR/check-xdg-data"
          mkdir -p "$HOME" "$XDG_DATA_HOME/omp"

          "$out/bin/omp" --version

          for nativeAddon in "$out"/lib/omp/pi_natives.*.node; do
            if [ -f "$nativeAddon" ]; then
              echo "unexpected standalone pi_natives addon installed next to omp: $nativeAddon"
              exit 1
            fi
          done

          runHook postInstallCheck
        '';

        passthru = {
          inherit bunDeps cargoDeps toolchainWithTarget;
        };

        meta = {
          description = "AI coding agent for the terminal";
          homepage = "https://github.com/can1357/oh-my-pi";
          license = lib.licenses.mit;
          mainProgram = "omp";
          platforms = [ system ];
        };
      };
    in
    {
      formatter.${system} = pkgs.nixfmt-rfc-style;

      packages.${system} = {
        default = package;
        "oh-my-pi" = package;
      };

      apps.${system}.default = {
        type = "app";
        program = "${package}/bin/omp";
      };
    };
}

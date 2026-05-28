{
  description = "Package oh-my-pi from source and upstream binaries";

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
      sourceData = builtins.fromJSON (builtins.readFile ./hashes.json);
      binData = builtins.fromJSON (builtins.readFile ./bin-hashes.json);

      runtimeLibraryPath = lib.makeLibraryPath [
        pkgs.stdenv.cc.cc.lib
        pkgs.zlib
      ];
      installCheckEnvironment = ''
        export HOME="$TMPDIR/check-home"
        export XDG_DATA_HOME="$TMPDIR/check-xdg-data"
        mkdir -p "$HOME" "$XDG_DATA_HOME/omp"
      '';
      relaxBunEngine = ''
        # Relax engines.bun to match the bun used for compilation. Upstream may
        # require a newer bun than nixpkgs carries, but the generated CLI runs
        # correctly with the compiler's embedded runtime.
        sed -i 's/"bun": ">=[0-9.]*"/"bun": ">='"$(bun --version)"'"/' \
          packages/utils/package.json
      '';
      commonMeta = {
        description = "AI coding agent for the terminal";
        homepage = "https://github.com/can1357/oh-my-pi";
        license = lib.licenses.mit;
        mainProgram = "omp";
        platforms = [ system ];
      };

      sourceVersion = sourceData.version;
      rustToolchainChannel = "nightly-2026-04-29";
      rustTarget = "x86_64-unknown-linux-gnu";
      sourceSrc = pkgs.fetchurl {
        url = "https://github.com/can1357/oh-my-pi/archive/refs/tags/v${sourceVersion}.tar.gz";
        hash = sourceData.srcHash;
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
        name = "${pname}-${sourceVersion}-bun-deps";
        src = sourceSrc;
        sourceRoot = "${pname}-${sourceVersion}";

        nativeBuildInputs = [ pkgs.bun ];
        strictDeps = true;
        dontConfigure = true;
        dontFixup = true;
        postPatch = relaxBunEngine;
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
        outputHash = sourceData.bunHash;
      };

      cargoDeps = rustPlatform.fetchCargoVendor {
        src = sourceSrc;
        sourceRoot = "${pname}-${sourceVersion}";
        hash = sourceData.cargoHash;
      };

      ohMyPi = pkgs.stdenv.mkDerivation {
        inherit pname cargoDeps;
        version = sourceVersion;
        src = sourceSrc;
        sourceRoot = "${pname}-${sourceVersion}";

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
        postPatch = relaxBunEngine;

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

          ${installCheckEnvironment}
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

        meta = commonMeta;
      };

      binVersion = binData.version;
      binAssetNames = {
        x86_64-linux = "omp-linux-x64";
      };
      binAssetName = binAssetNames.${system} or (throw "oh-my-pi-bin is not packaged for ${system}");
      binHash = binData.hashes.${system} or (throw "missing oh-my-pi-bin hash for ${system}");
      binSrc = pkgs.fetchurl {
        url = "https://github.com/can1357/oh-my-pi/releases/download/v${binVersion}/${binAssetName}";
        hash = binHash;
      };

      ohMyPiBin = pkgs.stdenv.mkDerivation {
        pname = "${pname}-bin";
        version = binVersion;
        src = binSrc;

        nativeBuildInputs = [
          pkgs.autoPatchelfHook
          pkgs.makeWrapper
        ];
        buildInputs = [
          pkgs.stdenv.cc.cc.lib
          pkgs.zlib
        ];
        strictDeps = true;
        dontUnpack = true;
        dontConfigure = true;
        dontBuild = true;
        dontStrip = true;

        installPhase = ''
          runHook preInstall

          install -Dm755 "$src" "$out/lib/omp/omp"
          makeWrapper "$out/lib/omp/omp" "$out/bin/omp" \
            --set PI_SKIP_VERSION_CHECK 1 \
            --prefix LD_LIBRARY_PATH : "${runtimeLibraryPath}"

          runHook postInstall
        '';

        doInstallCheck = true;
        installCheckPhase = ''
          runHook preInstallCheck

          ${installCheckEnvironment}
          "$out/bin/omp" --version

          runHook postInstallCheck
        '';

        meta = commonMeta;
      };
    in
    {
      formatter.${system} = pkgs.nixfmt-rfc-style;

      packages.${system} = {
        default = ohMyPi;
        "oh-my-pi" = ohMyPi;
        "oh-my-pi-bin" = ohMyPiBin;
      };

      apps.${system} = {
        default = {
          type = "app";
          program = "${ohMyPi}/bin/omp";
        };
        "oh-my-pi" = {
          type = "app";
          program = "${ohMyPi}/bin/omp";
        };
        "oh-my-pi-bin" = {
          type = "app";
          program = "${ohMyPiBin}/bin/omp";
        };
      };
    };
}

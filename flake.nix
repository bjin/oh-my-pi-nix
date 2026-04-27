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
      rustToolchainChannel = "nightly-2026-03-27";
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
          pkgs.zig
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
          export CARGO_HOME="$TMPDIR/cargo-home"
          mkdir -p "$HOME" "$XDG_CACHE_HOME" "$BUN_INSTALL_CACHE_DIR" "$CARGO_HOME"
          export LD_LIBRARY_PATH="${lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib ]}"
          export LIBCLANG_PATH="${pkgs.libclang.lib}/lib"

          cp -a ${bunDeps}/node_modules ./node_modules
          chmod -R u+w ./node_modules

          baselineTarget="$TMPDIR/target-baseline"
          modernTarget="$TMPDIR/target-modern"

          CARGO_TARGET_DIR="$baselineTarget" RUSTFLAGS='-C target-cpu=x86-64-v2' \
            cargo build --frozen --offline --release --target ${rustTarget} -p pi-natives
          install -Dm755 "$baselineTarget/${rustTarget}/release/libpi_natives.so" \
            packages/natives/native/pi_natives.linux-x64-baseline.node

          CARGO_TARGET_DIR="$modernTarget" RUSTFLAGS='-C target-cpu=x86-64-v3' \
            cargo build --frozen --offline --release --target ${rustTarget} -p pi-natives
          install -Dm755 "$modernTarget/${rustTarget}/release/libpi_natives.so" \
            packages/natives/native/pi_natives.linux-x64-modern.node

          bun --cwd=packages/coding-agent run generate-docs-index
          bun --cwd=packages/coding-agent run build

          runHook postBuild
        '';

        installPhase = ''
          runHook preInstall

          install -Dm755 packages/coding-agent/dist/omp "$out/lib/omp/omp"
          install -Dm755 packages/natives/native/pi_natives.linux-x64-baseline.node \
            "$out/lib/omp/pi_natives.linux-x64-baseline.node"
          install -Dm755 packages/natives/native/pi_natives.linux-x64-modern.node \
            "$out/lib/omp/pi_natives.linux-x64-modern.node"
          makeWrapper "$out/lib/omp/omp" "$out/bin/omp" \
            --set PI_SKIP_VERSION_CHECK 1 \
            --prefix LD_LIBRARY_PATH : "${runtimeLibraryPath}"
          install -Dm644 LICENSE "$out/share/licenses/${pname}/LICENSE"

          runHook postInstall
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

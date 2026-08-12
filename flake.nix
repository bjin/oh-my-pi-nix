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
      installShellCompletions = ''
        completion_dir="$TMPDIR/completions"
        completion_runtime_dir="$TMPDIR/completion-runtime"
        rm -rf "$completion_dir" "$completion_runtime_dir"
        mkdir -p "$completion_dir" "$completion_runtime_dir/home" "$completion_runtime_dir/xdg"

        HOME="$completion_runtime_dir/home" XDG_DATA_HOME="$completion_runtime_dir/xdg" \
          "$out/bin/omp" completions bash > "$completion_dir/omp.bash"
        HOME="$completion_runtime_dir/home" XDG_DATA_HOME="$completion_runtime_dir/xdg" \
          "$out/bin/omp" completions zsh > "$completion_dir/_omp"
        HOME="$completion_runtime_dir/home" XDG_DATA_HOME="$completion_runtime_dir/xdg" \
          "$out/bin/omp" completions fish > "$completion_dir/omp.fish"

        installShellCompletion --bash --name omp "$completion_dir/omp.bash"
        installShellCompletion --zsh --name _omp "$completion_dir/_omp"
        installShellCompletion --fish --name omp.fish "$completion_dir/omp.fish"
      '';
      installCheckCompletions = ''
        test -s "$out/share/bash-completion/completions/omp"
        test -s "$out/share/zsh/site-functions/_omp"
        test -s "$out/share/fish/vendor_completions.d/omp.fish"
      '';
      relaxBunEngine = ''
        # Relax engines.bun to match the bun used for compilation. Upstream may
        # require a newer bun than nixpkgs carries, but the generated CLI runs
        # correctly with the compiler's embedded runtime.
        sed -i 's/"bun": ">=[0-9.]*"/"bun": ">='"$(bun --version)"'"/' \
          packages/utils/package.json
      '';
      useLooseNativeAddons = ''
        # Nix ships native addons as loose .node files next to the compiled
        # executable. Reuse upstream's reset path so the standalone binary does
        # not embed a compressed native archive and the loader falls back to
        # those loose files from process.execPath's directory.
        substituteInPlace packages/natives/scripts/embed-native.ts \
          --replace-fail 'const reset = process.argv.includes("--reset");' \
            'const reset = true;'
      '';
      commonMeta = {
        description = "AI coding agent for the terminal";
        homepage = "https://github.com/can1357/oh-my-pi";
        license = lib.licenses.mit;
        mainProgram = "omp";
        platforms = [ system ];
      };

      sourceVersion = sourceData.version;
      sourceRev = sourceData.srcRev;
      rustToolchainChannel = "nightly-2026-07-28";
      rustTarget = "x86_64-unknown-linux-gnu";
      # Upstream drives the shipping addons through Bazel since 17.1.6, but the
      # rule (upstream `bazel/defs.bzl`, `crates/pi-natives/BUILD.bazel`) only
      # compiles the `pi_natives` cdylib at opt/thin-LTO/cgu=16/strip-symbols —
      # exactly the cargo `ci` profile — with a per-variant `-Ctarget-cpu` floor,
      # then renames it to the loader's canonical filename. Cargo covers that, so
      # the build stays Bazel-free. The napi CLI is not needed either:
      # `packages/natives/native/index.{js,d.ts}` are committed and regenerated
      # only when the Rust API changes.
      nativeAddonVariants = {
        baseline = "x86-64-v2";
        modern = "x86-64-v3";
      };
      nativeAddonFile = variant: "pi_natives.linux-x64-${variant}.node";
      buildNativeAddons = ''
        # pcre2-sys links a pkg-config libpcre2 when it finds one; upstream
        # release builds force the vendored static build instead.
        export PCRE2_SYS_STATIC=1
        # `audiopus_sys`' bundled opus fallback declares a
        # cmake_minimum_required below what CMake 4.x accepts unaided.
        export CMAKE_POLICY_VERSION_MINIMUM=3.5
      ''
      + lib.concatStrings (
        lib.mapAttrsToList (variant: targetCpu: ''

          echo "Building pi_natives addon: ${variant} (-Ctarget-cpu=${targetCpu})"
          RUSTFLAGS="-C target-cpu=${targetCpu}" \
            cargo build --offline --profile ci --package pi-natives --target ${rustTarget}
          install -Dm755 "$CARGO_TARGET_DIR/${rustTarget}/ci/libpi_natives.so" \
            "packages/natives/native/${nativeAddonFile variant}"
        '') nativeAddonVariants
      );
      installNativeAddons = lib.concatStrings (
        lib.mapAttrsToList (variant: _: ''
          install -Dm755 "packages/natives/native/${nativeAddonFile variant}" \
            "$out/lib/omp/${nativeAddonFile variant}"
        '') nativeAddonVariants
      );
      checkNativeAddons = lib.concatStrings (
        lib.mapAttrsToList (variant: _: ''
          test -x "$out/lib/omp/${nativeAddonFile variant}"
        '') nativeAddonVariants
      );
      sourceSrc = pkgs.fetchgit {
        url = "https://github.com/can1357/oh-my-pi.git";
        rev = sourceRev;
        deepClone = false;
        fetchSubmodules = false;
        fetchTags = false;
        leaveDotGit = false;
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
        hash = sourceData.cargoHash;
      };

      ohMyPi = pkgs.stdenv.mkDerivation {
        inherit pname cargoDeps;
        version = sourceVersion;
        src = sourceSrc;

        nativeBuildInputs = [
          pkgs.autoPatchelfHook
          pkgs.bun
          # `audiopus_sys` builds its vendored static libopus fallback with CMake.
          pkgs.cmake
          pkgs.makeWrapper
          pkgs.installShellFiles
          pkgs.pkg-config
          toolchainWithTarget
          rustPlatform.cargoSetupHook
          # `maudio-sys` generates bindings with libclang; this hook also provides
          # its Nix libc include flags.
          rustPlatform.bindgenHook
        ];

        buildInputs = [
          pkgs.stdenv.cc.cc.lib
          # `audiopus_sys` enables its `static` feature; pkg-config locates this
          # libopus archive instead of falling back to the bundled CMake build.
          pkgs.opus
          pkgs.zlib
        ];
        strictDeps = true;
        # CMake belongs to `audiopus_sys`, not this derivation's source root.
        dontUseCmakeConfigure = true;
        dontStrip = true;
        postPatch = ''
          ${relaxBunEngine}
          ${useLooseNativeAddons}
        '';

        buildPhase = ''
          runHook preBuild

          export HOME="$TMPDIR/home"
          export XDG_CACHE_HOME="$TMPDIR/xdg-cache"
          export BUN_INSTALL_CACHE_DIR="$TMPDIR/bun-install-cache"
          export CARGO_TARGET_DIR="$TMPDIR/cargo-target"
          mkdir -p "$HOME" "$XDG_CACHE_HOME" "$BUN_INSTALL_CACHE_DIR" "$CARGO_TARGET_DIR"
          export LD_LIBRARY_PATH="${lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib ]}"

          cp -a ${bunDeps}/node_modules ./node_modules
          chmod -R u+w ./node_modules
          ${buildNativeAddons}

          bun --cwd=packages/coding-agent run build

          runHook postBuild
        '';

        installPhase = ''
          runHook preInstall

          install -Dm755 packages/coding-agent/dist/omp "$out/lib/omp/omp"
          ${installNativeAddons}
          makeWrapper "$out/lib/omp/omp" "$out/bin/omp" \
            --set PI_SKIP_VERSION_CHECK 1 \
            --prefix LD_LIBRARY_PATH : "${runtimeLibraryPath}"
          install -Dm644 LICENSE "$out/share/licenses/${pname}/LICENSE"

          runHook postInstall
        '';

        preFixup = ''
          installShellCompletionsHook() {
            ${installShellCompletions}
          }
          postFixupHooks+=(installShellCompletionsHook)
        '';

        doInstallCheck = true;
        installCheckPhase = ''
          runHook preInstallCheck

          ${installCheckEnvironment}
          smoke_output=$("$out/bin/omp" --smoke-test)
          if [ "$smoke_output" != "smoke-test: ok" ]; then
            echo "unexpected smoke test output: $smoke_output"
            exit 1
          fi
          # This fixture clears `omp read`'s summary gate and reaches the
          # tree-sitter-haskell allocation path that previously corrupted the heap.
          "$out/bin/omp" read ${./Crash.hs} > "$TMPDIR/haskell-crash-regression"
          test -s "$TMPDIR/haskell-crash-regression"

          ${installCheckCompletions}

          ${checkNativeAddons}
          if [ -e "$XDG_DATA_HOME/omp/natives" ] || [ -e "$HOME/.omp/natives" ]; then
            echo "omp wrote native addons to a user cache"
            exit 1
          fi

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
          pkgs.installShellFiles
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

        preFixup = ''
          installShellCompletionsHook() {
            ${installShellCompletions}
          }
          postFixupHooks+=(installShellCompletionsHook)
        '';

        doInstallCheck = true;
        installCheckPhase = ''
          runHook preInstallCheck

          ${installCheckEnvironment}
          smoke_output=$("$out/bin/omp" --smoke-test)
          if [ "$smoke_output" != "smoke-test: ok" ]; then
            echo "unexpected smoke test output: $smoke_output"
            exit 1
          fi

          ${installCheckCompletions}

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

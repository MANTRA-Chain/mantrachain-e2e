{
  lib,
  stdenv,
  buildGoModule,
  staticBuildGoModule,
  fetchFromGitHub,
  fetchurl,
  pkgsStatic,
}:
{
  version,
  pname ? "mantrachain",
  owner ? "MANTRA-Chain",
  repo ? "mantrachain",
  rev,
  hash,
  vendorHash,
  # no default: it must track the version's go.mod, and a stale inherited
  # default links the wrong libwasmvm
  wasmvmVersion,
  nativeByteOrder ? true,
}:
let
  # Use static packages for Linux to ensure musl compatibility.
  # The Go module builder is caller-provided so each mantrachain version can be
  # compiled with the Go toolchain it requires (older releases pin Go 1.25).
  buildStdenv = if stdenv.isLinux then pkgsStatic.stdenv else stdenv;
  buildGoModule' = if stdenv.isLinux then staticBuildGoModule else buildGoModule;

  wasmvmHashesByVersion = {
    "v3.0.0" = {
      darwin = "sha256-D3D8Ad1Jd8jRwlBDb6eVoMGlPDlKohI4rt0xe+kOdlQ=";
      linux-x86_64 = "sha256-zv5z8Mqlqeq6NzPGOc31BAxHRqk8IGcLpskof+OUSLo=";
      linux-aarch64 = "sha256-oElptPkxvh0uLz8jE6aKIKICaT9nVZ96rx3ZclCCOuw=";
    };
    "v3.0.7" = {
      darwin = "sha256-ZQSO+VgiuNLzNlYj1TsX1AZODF5XKD7JHET0jFC/TP0=";
      linux-x86_64 = "sha256-SezXDaKBtu4IsxdwpUu1KdHelrPlQBPgJd+fDDn/9/Q=";
      linux-aarch64 = "sha256-7z4xJeHOWIqbxpj2laGkeTQyuZA6CSgBjA14cuh0zJc=";
    };
  };

  wasmvmHashes =
    wasmvmHashesByVersion.${wasmvmVersion} or (throw
      "Unknown wasmvm version ${wasmvmVersion}; add its libwasmvm hashes to mantrachain-builder.nix"
    );

  # Download wasmvm libraries as fixed-output derivations
  wasmvmLibs = {
    darwin = fetchurl {
      url = "https://github.com/CosmWasm/wasmvm/releases/download/${wasmvmVersion}/libwasmvmstatic_darwin.a";
      sha256 = wasmvmHashes.darwin;
    };
    linux-x86_64 = fetchurl {
      url = "https://github.com/CosmWasm/wasmvm/releases/download/${wasmvmVersion}/libwasmvm_muslc.x86_64.a";
      sha256 = wasmvmHashes.linux-x86_64;
    };
    linux-aarch64 = fetchurl {
      url = "https://github.com/CosmWasm/wasmvm/releases/download/${wasmvmVersion}/libwasmvm_muslc.aarch64.a";
      sha256 = wasmvmHashes.linux-aarch64;
    };
  };

  wasmvmLib =
    if buildStdenv.isDarwin then
      wasmvmLibs.darwin
    else if buildStdenv.isLinux && buildStdenv.hostPlatform.isAarch64 then
      wasmvmLibs.linux-aarch64
    else if buildStdenv.isLinux then
      wasmvmLibs.linux-x86_64
    else
      throw "Unsupported platform for wasmvm";

  tags =
    [
      "ledger"
      "ledger_zemu"
      "netgo"
      "osusergo"
      "pebbledb"
    ]
    ++ lib.optionals nativeByteOrder [ "nativebyteorder" ]
    ++ lib.optionals buildStdenv.isDarwin [ "static_wasm" ]
    ++ lib.optionals buildStdenv.isLinux [ "muslc" ];

  ldflags =
    [
      "-X github.com/cosmos/cosmos-sdk/version.Name=mantrachain"
      "-X github.com/cosmos/cosmos-sdk/version.AppName=${pname}"
      "-X github.com/cosmos/cosmos-sdk/version.Version=${version}"
      "-X github.com/cosmos/cosmos-sdk/version.BuildTags=${lib.concatStringsSep "," tags}"
      "-X github.com/cosmos/cosmos-sdk/version.Commit=${rev}"
    ]
    ++ [
      "-w"
      "-s"
      "-linkmode=external"
    ]
    ++ lib.optionals buildStdenv.isLinux [
      "-extldflags '-static -lm'"
    ];

in
buildGoModule' rec {
  inherit
    pname
    version
    tags
    ldflags
    vendorHash
    ;
  stdenv = buildStdenv;
  src = fetchFromGitHub {
    inherit owner repo rev hash;
  };
  proxyVendor = true;
  subPackages = [ "cmd/mantrachaind" ];
  env.CGO_ENABLED = "1";

  preBuild = ''
    mkdir -p $TMPDIR/lib
    cp ${wasmvmLib} $TMPDIR/lib/$(basename ${wasmvmLib.name})
    export CGO_LDFLAGS="-L$TMPDIR/lib $CGO_LDFLAGS"
  '';

  doCheck = false;
  meta = with lib; {
    description = "Official implementation of the mantra protocol";
    homepage = "https://www.mantrachain.io/";
    license = licenses.asl20;
    mainProgram = "mantrachaind" + buildStdenv.hostPlatform.extensions.executable;
    platforms = platforms.all;
  };
}

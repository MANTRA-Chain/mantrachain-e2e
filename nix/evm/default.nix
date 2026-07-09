{
  lib,
  stdenv,
  buildGo126Module,
  fetchFromGitHub,
  rev ? "dirty",
  nativeByteOrder ? true, # nativeByteOrder mode will panic on big endian machines
  fetchurl,
  pkgsStatic,
}:
let
  version = "v0.5.0";
  pname = "evmd";

  # Use static packages for Linux to ensure musl compatibility
  buildStdenv = if stdenv.isLinux then pkgsStatic.stdenv else stdenv;
  buildGoModule' = if stdenv.isLinux then pkgsStatic.buildGo126Module else buildGo126Module;

  tags =
    [
      "ledger"
      "ledger_zemu"
      "netgo"
      "osusergo"
      "pebbledb"
    ]
    ++ lib.optionals nativeByteOrder [ "nativebyteorder" ]
    ++ lib.optionals buildStdenv.isLinux [ "muslc" ];

  ldflags =
    [
      "-X github.com/cosmos/cosmos-sdk/version.Name=evmd"
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
    ;
  stdenv = buildStdenv;
  src = fetchFromGitHub {
    owner = "cosmos";
    repo = "evm";
    rev = "374f3d5c24387bf4e275ec430e6cf6e4bf5a093c";
    hash = "sha256-dRIJNxYuVSqyeQYL140KZTVFE8DBnmXwhLDav+l25mw=";
  };
  
  vendorHash = "sha256-SIZI4mjHf/kYSi4MN9spxwb6YzUPmziywvcUInPhBn0=";
  proxyVendor = true;
  sourceRoot = "source/evmd";
  subPackages = [ "cmd/evmd" ];
  env.CGO_ENABLED = "1";

  preBuild = ''
    mkdir -p $TMPDIR/lib
    export CGO_LDFLAGS="-L$TMPDIR/lib $CGO_LDFLAGS"
    export GOTOOLCHAIN=local
  '';

  doCheck = false;
  meta = with lib; {
    description = "An EVM compatible framework for blockchain development with the Cosmos SDK";
    homepage = "https://github.com/cosmos/evm";
    license = licenses.asl20;
    mainProgram = "evmd" + buildStdenv.hostPlatform.extensions.executable;
    platforms = platforms.all;
  };
}

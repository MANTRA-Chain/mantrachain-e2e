{
  lib,
  stdenv,
  buildGo125Module,
  fetchFromGitHub,
  rev ? "dirty",
  nativeByteOrder ? true, # nativeByteOrder mode will panic on big endian machines
  fetchurl,
  pkgsStatic,
}:
let
  version = "v1";
  pname = "inveniamd";

  # Use static packages for Linux to ensure musl compatibility
  buildPackages = if stdenv.isLinux then pkgsStatic else { inherit stdenv buildGo125Module; };
  buildStdenv = buildPackages.stdenv;
  buildGoModule' = if stdenv.isLinux 
    then buildPackages.buildGo125Module
    else buildGo125Module;

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
      "-X github.com/cosmos/cosmos-sdk/version.Name=inveniamd"
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
    owner = "MANTRA-Chain";
    repo = "inveniam";
    rev = "c6bd2abffd7bd20d014ffddf7ffd2162422ad42f";
    hash = "";
  };
  
  vendorHash = "";
  proxyVendor = true;
  sourceRoot = "source/inveniamd";
  subPackages = [ "cmd/inveniamd" ];
  env.CGO_ENABLED = "1";

  preBuild = ''
    mkdir -p $TMPDIR/lib
    export CGO_LDFLAGS="-L$TMPDIR/lib $CGO_LDFLAGS"
    export GOTOOLCHAIN=local
  '';

  doCheck = false;
  meta = with lib; {
    description = "Inveniam is a global real-world assets platform built on blockchain technology";
    homepage = "https://github.com/MANTRA-Chain/inveniam";
    license = licenses.asl20;
    mainProgram = "inveniamd" + buildStdenv.hostPlatform.extensions.executable;
    platforms = platforms.all;
  };
}

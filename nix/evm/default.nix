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
  version = "v0.5.0";
  pname = "evmd";

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
    owner = "yihuang";
    repo = "evm";
    rev = "4b0c8b2878abba023863653c0c194038d18a4c60";
    hash = "sha256-DTfYY0aaIkUoL0keRUImwDJmfHFzlTUGzk78btSrxmU=";
  };
  
  vendorHash = "sha256-Wl5kAGfn2C2Gwx7BjjIrcZfpeduoDc3YNhlAnjaa7TA=";
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

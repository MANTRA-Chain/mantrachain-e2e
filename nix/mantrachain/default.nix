{
  lib,
  stdenv,
  buildGo125Module,
  fetchFromGitHub,
  fetchurl,
  pkgsStatic,
}:
let
  builder = import ../mantrachain-builder.nix {
    inherit lib stdenv buildGo125Module fetchFromGitHub fetchurl pkgsStatic;
  };
in
builder {
  version = "v8";
  owner = "MANTRA-Chain";
  rev = "c2ac25146ab79e596a23873dee6f80c7d58cd25b";
  hash = "sha256-wntTBocswbo/Lut+/FTn+y50pAeSJJdyV1H3CJuglwI=";
  vendorHash = "sha256-h26r91LLIqy/xz+sFuvpgNMKMCLcNvQJs53Jmri7dM4=";
}

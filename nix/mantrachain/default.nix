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
  rev = "fc5efcd2917eab3d1eff2a40a22045776498b386";
  hash = "sha256-A1kBrMfxj6v37z7CiKOyq8PwTn9nDPQCeGpmv1wch6A=";
  vendorHash = "sha256-rzI3PBpVatgVrLpr4+Q5CS9+61afFsrgFMbfGPW/IFo=";
}

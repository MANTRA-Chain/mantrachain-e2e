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
  version = "v7-provider";
  owner = "MANTRA-Chain";
  rev = "074c1d7312e16991bc22106a3fe9fe4113fc4a04";
  hash = "sha256-YsLBw/ZLvzKIsCoQpMaHQGRpMYogcekeQG5ladDOjk0=";
  vendorHash = "sha256-rzI3PBpVatgVrLpr4+Q5CS9+61afFsrgFMbfGPW/IFo=";
}
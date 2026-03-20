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
  rev = "15578bcae66377dd48167214afb665c45e7f6116";
  hash = "sha256-WW0vD/pJ/80BP4VFpF3BpPjIOJXU4ZJOcXpeSOx44I8=";
  vendorHash = "sha256-h26r91LLIqy/xz+sFuvpgNMKMCLcNvQJs53Jmri7dM4=";
}

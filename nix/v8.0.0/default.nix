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
  version = "v8.0.0";
  owner = "MANTRA-Chain";
  rev = "03a390377002ab24bb347eac41d91728e09b7c7f";
  hash = "sha256-7U9oo6+bOeHVrs+7ZS74BSiLTT8BDAiL4nDSvCp+Taw=";
  vendorHash = "sha256-T2bVw1ItFiRy4H3TjGwhUiyrH0zhqTDViqg3OxuZXKE=";
}

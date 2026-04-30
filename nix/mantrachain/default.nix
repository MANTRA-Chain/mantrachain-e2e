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
  version = "v8.1.0";
  owner = "MANTRA-Chain";
  rev = "17ac3c9c1f23718074dd7c329916d16b68348112";
  hash = "sha256-q+9dmbM4wHD8rHOVNc1zpaX0wod84YUpJG25EsAWLX8=";
  vendorHash = "sha256-Yn8c7H4Ihg6Wr87Xt4geyn+RSceg4t1+2ba9+iFYq18=";
}

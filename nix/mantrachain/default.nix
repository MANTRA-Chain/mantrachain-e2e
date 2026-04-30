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
  rev = "e7140121d605a86025526291e5743c0494617a8b";
  hash = "sha256-kx6T+4HuqUl2C0a2TaGZ4BhNh3mXoNem5lnuuGFidvE=";
  vendorHash = "sha256-Yn8c7H4Ihg6Wr87Xt4geyn+RSceg4t1+2ba9+iFYq18=";
}

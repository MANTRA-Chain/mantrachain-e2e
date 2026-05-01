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
  version = "v8.1.1";
  owner = "MANTRA-Chain";
  rev = "eb92b6bac5f8e7a2406cc21de6b24941e9b6ddb1";
  hash = "sha256-v0w9bCunOWahAAU5jiwLDRJwpBSsC7Y2VQEnaqX24ZU=";
  vendorHash = "sha256-Yn8c7H4Ihg6Wr87Xt4geyn+RSceg4t1+2ba9+iFYq18=";
}

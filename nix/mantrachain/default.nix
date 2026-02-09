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
  rev = "a7e7e0736e894f4c8ff29097044c5fa0ed2057ec";
  hash = "sha256-sSVzuVvbI6JnmIubHRTXY6aUi6yXu/5rfou+JYmX1fU=";
  vendorHash = "sha256-eL/vouCkuZsTOXD7OLMeaJJvV0Zk5N4mWz/CGWc9KDo=";
}

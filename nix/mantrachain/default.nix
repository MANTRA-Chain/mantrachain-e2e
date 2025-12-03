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
  version = "v7";
  owner = "MANTRA-Chain";
  rev = "8d8294c5cf3603d3d9b35689245d0a3df1b6b3e2";
  hash = "sha256-IPsRLdKeqi80nXnDI4JgQUO+abODDhwp9+IlEuOQH74=";
  vendorHash = "sha256-F9S6ddxqBmZz8JNSgM7dfGK9GBnX/+EqrG+gQjMaAV4=";
}

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
  rev = "056853e9703ca1f1783d9764fd3f44a59e9f44ba";
  hash = "sha256-rfrO0Req1gzKaEWZGdgmYZPjI+prmKctIqRPjW2RunQ=";
  vendorHash = "sha256-F9S6ddxqBmZz8JNSgM7dfGK9GBnX/+EqrG+gQjMaAV4=";
}

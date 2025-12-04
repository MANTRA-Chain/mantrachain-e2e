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
  rev = "778e7815605fe8b5773d1ac9b9b0dd275870812e";
  hash = "sha256-QaKlZcTq7xVKh4OzwkwjYR28PST6lPX9Ple1DR21obY=";
  vendorHash = "sha256-F9S6ddxqBmZz8JNSgM7dfGK9GBnX/+EqrG+gQjMaAV4=";
}

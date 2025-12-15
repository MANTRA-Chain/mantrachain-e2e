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
  rev = "88307ed5c9bddd3319e4cfc7e07c02d5dba941d7";
  hash = "sha256-waAMqnlp96/NtTgyqedNozzxsfjfvudvhOpyvqvq8zM=";
  vendorHash = "sha256-EdUU6EfniAs/wPuVGXTfuVgCgpABrQZAWs/5XejsJuw=";
}

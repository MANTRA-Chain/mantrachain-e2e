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
  rev = "3867f8fca1780c3d8ae6ee40fe571743ca530939";
  hash = "sha256-qWqZSvnxTnOKsLm5pqnbOpF99huFdN7lMYF17XaRnVs=";
  vendorHash = "sha256-F9S6ddxqBmZz8JNSgM7dfGK9GBnX/+EqrG+gQjMaAV4=";
}

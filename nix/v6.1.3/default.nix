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
  version = "v6.1.3";
  owner = "MANTRA-Chain";
  rev = "b196197c1c9cb0e789f8866a016d0770e68a9b0b";
  hash = "sha256-dowfvOwQHRanbR51PIiXaNMz3/5YcLWrVZGxhlqH3G4=";
  vendorHash = "sha256-5cJMWgyYiCBsShLi1+ytIqSYisc1qb7I9crVkKUmsPc=";
}
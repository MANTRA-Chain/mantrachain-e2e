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
  rev = "ec36c5c0d77d7d4d04f0327e16ae3e04496094de";
  hash = "sha256-cp0Eq5Izd0ko+mLE7tHbwDqneZclp/XgvDgVxzH6E6g=";
  vendorHash = "sha256-NL2pMF6cK9WeqvN4vxAgMTfn+yGtUEVXH5M3fcLiYP0=";
}

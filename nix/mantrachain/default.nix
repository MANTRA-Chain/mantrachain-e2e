{
  lib,
  stdenv,
  buildGo123Module,
  fetchFromGitHub,
  fetchurl,
  pkgsStatic,
}:
let
  builder = import ../mantrachain-builder.nix {
    inherit lib stdenv buildGo123Module fetchFromGitHub fetchurl pkgsStatic;
  };
in
builder {
  version = "v7.0.0-rc2-supply";
  owner = "MANTRA-Chain";
  rev = "eb9c1212e6c6d066ab2ae9d2e5503114fcd4b570";
  hash = "sha256-jsSnlfYNklQuPgy4hIVr5xPbK4s7BpXV8RJQkvOPChw=";
  vendorHash = "sha256-aKUC7Arj8EvS3eBbJEOj9Wn51CZGedd2h0nAejFYChc=";
}
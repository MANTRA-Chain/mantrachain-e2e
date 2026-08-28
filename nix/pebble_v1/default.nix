# v8.4.0 on pebble v1, carrying the format ratchet
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
  version = "v8.4.0";
  owner = "MANTRA-Chain";
  rev = "1c47e01d4559feddb634f45fa28804c6093301b3";
  hash = "sha256-6rVOxqle2+8rc3by7ibLCti6ye9c1KEvPsMJaLCxh9w=";
  vendorHash = "sha256-/tJUPHXtGAWaYIDyX3Xo6bC62fLeGP+xzFSEz7t9U3A=";
}

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
  version = "v7.0.0-rc0";
  owner = "MANTRA-Chain";
  rev = "e7dc59c48aff8a48526e08e46e208bcc74b32bfd"; 
  hash = "sha256-kRsrs3ArX5z+6OAmCu1NaZ+rO33zpYpGlDPuJz4D6IY=";
  vendorHash = "sha256-9bB9p2vapLhnnXtxVKguKn/vAf4F1BOq8feo79zOU0w=";
}

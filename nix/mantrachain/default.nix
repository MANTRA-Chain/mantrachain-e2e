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
  version = "v8.1.1";
  owner = "MANTRA-Chain";
  rev = "a937e7cf7c948ae9bb1deae10855ccd5e29c58e0";
  hash = "sha256-xH+dhWNJe3ZPk09boHQnuf8L0WAYkUjJfLDy1By9K9w=";
  vendorHash = "sha256-92KVzbNOz1hdneqldGAixzgBSsfLfQ44OsnNc/TJfzI=";
}

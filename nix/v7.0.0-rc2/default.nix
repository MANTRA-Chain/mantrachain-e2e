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
  version = "v7.0.0-rc2";
  owner = "MANTRA-Chain";
  rev = "104de9bd724c4fb0815640180d39b866262c41ae";
  hash = "sha256-gMSwBcl2l3QPYdNVe/a0L7ABdFeNWIJmzCIAx8J8vKg=";
  vendorHash = "sha256-Zj+E0T/xx+D5UOrk2bI5uemgkAtZn98w3/AaWqP0CkY=";
}
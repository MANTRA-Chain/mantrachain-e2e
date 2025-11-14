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
  version = "v7.0.0-rc1";
  owner = "mmsqe";
  rev = "cbb7153740ac9df19227ba0bde5d0228ee425933"; 
  hash = "sha256-zvgX95OKiavTaq+wOD04ix0LDhPipt/401LwXY6QAHo=";
  vendorHash = "sha256-LxcFv21uij3jHDag4ETzYvsw8R7yxbA0oDe+MkZn5k4=";
}

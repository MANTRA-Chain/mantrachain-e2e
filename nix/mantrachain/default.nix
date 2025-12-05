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
  owner = "mmsqe";
  rev = "4d1bbbbf9c0bb6a52e9098714a4f6b3d811195dc";
  hash = "sha256-B+aDbrRYh1iEBnJ7Vu/gJtLOcmwMRwpLOQp39AufKV4=";
  vendorHash = "sha256-Zj+E0T/xx+D5UOrk2bI5uemgkAtZn98w3/AaWqP0CkY=";
}

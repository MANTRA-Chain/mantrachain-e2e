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
  rev = "f08218839600ecf2e1508d1e91736d81aec28563";
  hash = "sha256-PJ47+QZksBvQFZMmvFBE9E0zpEy1KJeGHT5WYmnRtlQ=";
  vendorHash = "sha256-xsFbHrCd824RVkbLAvap7WIb5GOCdvtMuw148cANWrA=";
}

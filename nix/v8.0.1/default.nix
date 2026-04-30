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
  version = "v8.0.1";
  owner = "MANTRA-Chain";
  rev = "cdd06462d0630db809c09d6f8a29f90a932942a1";
  hash = "sha256-h2YYquMTXOJ9brKhuQDhdK4XoDmawTDi4qHjCm899fU=";
  vendorHash = "sha256-inc8RP6/QhTXJGageGJR6NfVDj7rgmTgSxVNlRpMboc=";
}

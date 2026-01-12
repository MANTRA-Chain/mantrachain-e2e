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
  version = "v7.0.0";
  owner = "MANTRA-Chain";
  rev = "8c129dde115040130dd2cd1f177c7ae0b03d4634";
  hash = "sha256-iWnJ9c+mSv+y03jUafD9RPs1vV26Tuhi+6LLQucspB0=";
  vendorHash = "sha256-T2kHD+NBRYoFHzcsUGEjqfWFelhEQKzyKBXrKRfgAKQ=";
}
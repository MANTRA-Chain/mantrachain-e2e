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
  rev = "f0ad92aa60e5adc8c545a943b5c1b2cacfa8f3aa";
  hash = "sha256-sO/m43x+CwS/wiQAE7336pEsT4p6vyvS5tIkOoDDIj4=";
  vendorHash = "sha256-zL0GxEZKQIVF0lPfydG+lhB/ECKKo1hSfrnilTIuHL0=";
}

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
  rev = "e826e619b3c800d94a2734b17bfc58c4247165f7"; 
  hash = "sha256-KqLvAxFV7ThT8fc2U7ma16Dco6T+Xvw7P/hYr/Ptfw0=";
  vendorHash = "sha256-t3gcCbKweM17LfQpEfcMfZrHEb5obEpBtD3QGaJ3r5Y=";
}
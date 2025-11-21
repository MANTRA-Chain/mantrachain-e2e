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
  version = "v7.0.0-rc2-supply";
  owner = "yihuang";
  rev = "e6a1055b34bbaf1760c6a5184bf730ae0d72a664";
  hash = "sha256-pkn8aYlEPJnci92sNc+k01eni5nhtTFLj7aPqgdPO8I=";
  vendorHash = "sha256-YxrGyDcGxZWA+qsh3gwaSOCEqx7IoTd+BcdReLqbpBg=";
}
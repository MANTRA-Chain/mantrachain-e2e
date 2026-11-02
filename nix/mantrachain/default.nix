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
  version = "v8.8.0";
  owner = "MANTRA-Chain";
  rev = "05a2751888149197527878ae1668e7bbc4e2fd54";
  hash = "sha256-NPtTO8uTA723v2rS1hNjPHIvtPB1sDt/2F/kWko7SjY=";
  vendorHash = "sha256-WxIMmApR+PdFvwqkEFIKEYYp6O5FpXWdKPkqyIoIDIM=";
  wasmvmVersion = "v3.0.8";
}

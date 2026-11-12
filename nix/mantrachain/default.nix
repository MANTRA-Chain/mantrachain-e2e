{
  lib,
  stdenv,
  buildGo125Module,
  buildGo126Module,
  fetchFromGitHub,
  fetchurl,
  pkgsStatic,
}:
let
  builder = import ../mantrachain-builder.nix {
    inherit lib stdenv buildGo125Module buildGo126Module fetchFromGitHub fetchurl pkgsStatic;
  };
in
builder {
  version = "v8.9.0";
  owner = "MANTRA-Chain";
  rev = "95280448968fb4be035024a9959c871b5717f84d";
  hash = "sha256-MoB9GRYkjFPMCfCOhqPgkCy+TdTE/mZrJTiF67jJ8S4=";
  vendorHash = "sha256-WxIMmApR+PdFvwqkEFIKEYYp6O5FpXWdKPkqyIoIDIM=";
  wasmvmVersion = "v3.0.8";
  goVersion = "1.26";
}

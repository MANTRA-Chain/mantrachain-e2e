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
  rev = "9d4f642cb263210651865e7a7f8d3f003fab6cfb";
  hash = "sha256-EN/E2KCza5f2eyoulczC9SeAj1zOVFJJ8z6UcQFRD/Q=";
  vendorHash = "sha256-WxIMmApR+PdFvwqkEFIKEYYp6O5FpXWdKPkqyIoIDIM=";
  wasmvmVersion = "v3.0.8";
  goVersion = "1.26";
}

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
  rev = "beeaa8e824a57a90c61484ecc241f65a19ed6b24";
  hash = "sha256-LM7nU4r9CwSKDYGVjfLzdRKI+vjGfHKoUPxt/axN96E=";
  vendorHash = "sha256-WxIMmApR+PdFvwqkEFIKEYYp6O5FpXWdKPkqyIoIDIM=";
  wasmvmVersion = "v3.0.8";
  goVersion = "1.26";
}

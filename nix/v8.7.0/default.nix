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
  version = "v8.7.0";
  owner = "MANTRA-Chain";
  rev = "7f562fb4763b681ed708587db6216cadfd80b865";
  hash = "sha256-6CQxOwptuz4ukER3HZTz7Q7y9W3htHUDoc2Y1P/K0vo=";
  vendorHash = "sha256-vb1gCuy23aSkRAcN2vsI0i4O0wxUyVwC6L8vSDjSQo8=";
  wasmvmVersion = "v3.0.8";
}

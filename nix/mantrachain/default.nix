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
  version = "v8.5.0";
  owner = "MANTRA-Chain";
  rev = "2ec20cea34d2ce5dde3475ea9b338d18c440de5e";
  hash = "sha256-8tkYhwWjhg0QqTwW/gx+cMsVz8zoCcykZF43oU7GAYU=";
  vendorHash = "sha256-PWqKgKW5ChQQjshSXshdn1biacCWuptsbK6tYoEVMhs=";
}

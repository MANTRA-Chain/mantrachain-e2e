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
  version = "v7.0.0-rc2";
  owner = "MANTRA-Chain";
  rev = "9fa1dcb3cc7d8b51582b03089c3f2b70988cfee0";
  hash = "sha256-jZdb4BxpIq8ux9VlWGAqAyi3QVe6eW8EICYouJf28Ko=";
  vendorHash = "sha256-F9S6ddxqBmZz8JNSgM7dfGK9GBnX/+EqrG+gQjMaAV4=";
}
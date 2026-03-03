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
  rev = "9431b3c9850d1f97c791dc68c73beef05d108a8e";
  hash = "sha256-+GBIs3/7cfbZ9sM47NYt2FM5DUeRRYM1sH2j4+bgkDc=";
  vendorHash = "sha256-kTl4V7Q8IJljRcmRT7m8GerNsIMBSBNjFu8VaMMzXtc=";
}

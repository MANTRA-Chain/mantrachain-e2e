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
  version = "v8.1.1";
  owner = "MANTRA-Chain";
  rev = "8aba8560d2e21fe2cb8394472178e093275051e7";
  hash = "sha256-GxCv5g8H3xRUTNF7o6rDI05B3+pPw0JokdrPrRxCvK8=";
  vendorHash = "sha256-Yn8c7H4Ihg6Wr87Xt4geyn+RSceg4t1+2ba9+iFYq18=";
}

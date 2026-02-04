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
  rev = "3ae496a16098b62f67a7fd41025206b1e806a5a5";
  hash = "sha256-Z8SmEqTqaBpyolZMrzdnYr0HtjnSgjq9M9kQmaAcMvU=";
  vendorHash = "sha256-VE7jWsokGZ1hOI3E1XKhNiOjhfqvsidppAT2JE1LcvU=";
}

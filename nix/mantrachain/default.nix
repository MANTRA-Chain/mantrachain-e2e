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
  version = "v7";
  owner = "mmsqe";
  rev = "55da41782d9d99874cc00e8ce1e6cb139f9bb96f";
  hash = "sha256-9ZWtWUSZ/99Hlaz/z7c/aUqSS5D+/mw+d48nfPcjBGU=";
  vendorHash = "sha256-F9S6ddxqBmZz8JNSgM7dfGK9GBnX/+EqrG+gQjMaAV4=";
}

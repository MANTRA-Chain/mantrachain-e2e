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
  rev = "fa5891d19439e7cd5d0db1e27857e09a0dd41514";
  hash = "sha256-e+Z8wRl5jzctxWeynbIdLYRyJIrn3XuvMCr5VXlSSWw=";
  vendorHash = "sha256-4k/8HmmCKJx4Sqruw48hR73ThQxzuVX5oIGBGH3U580=";
}

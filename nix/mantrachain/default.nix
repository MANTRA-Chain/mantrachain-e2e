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
  owner = "MANTRA-Chain";
  rev = "d2b3eeec5f3b16c8a0a0dc1c4941533ed415a1f5";
  hash = "sha256-mIV/IInqE0WQpnErpe3RnWv5vGwEcdtL6XPxcUMN/sg=";
  vendorHash = "sha256-gA6Un795JTcT+0oXVAsc8KLCywJVnwpHhznqWZcrhmA=";
}

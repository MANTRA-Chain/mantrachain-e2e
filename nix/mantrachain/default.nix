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
  version = "v8.4.0";
  owner = "MANTRA-Chain";
  rev = "65ef9e73272f45c117f8c47c231ea3c11ac258cf";
  hash = "sha256-T0TyuM5Y8Hq33UOhG1pWzAXaWdlr+C6H/lVXybqnVlk=";
  vendorHash = "sha256-Wpc6txVSvr2SIwzK8pmj4vwH6K5y3iOXHvMH77/4Ayg=";
}

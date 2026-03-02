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
  rev = "5ac5a1bfbfb967c7ea56c1ae554ff76b5927209a";
  hash = "sha256-Dq7394FX0keuZZs0COa0fG4d2cEK3cUNKkifs3aDOwA=";
  vendorHash = "sha256-02McDfDYsRM8UWUlo1YNRmcuhahh1f7R4Cgsx/vnahQ=";
}

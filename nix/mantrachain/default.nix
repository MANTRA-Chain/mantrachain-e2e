{
  lib,
  stdenv,
  buildGo126Module,
  fetchFromGitHub,
  fetchurl,
  pkgsStatic,
}:
let
  builder = import ../mantrachain-builder.nix {
    inherit lib stdenv fetchFromGitHub fetchurl pkgsStatic;
    buildGoModule = buildGo126Module;
    staticBuildGoModule = pkgsStatic.buildGo126Module;
  };
in
builder {
  version = "v8.5.0";
  wasmvmVersion = "v3.0.7";
  rev = "457d5af9e58df816d44c559c87eee3a3bd361357";
  hash = "sha256-oJiWR3/2lWw6lqWuGaLcYCcBV8XwDtdqLVz+S7zz/1g=";
  vendorHash = "sha256-GcJSuxbApkJ7PzGleWa7Or3jUZiWlrJIJWIdIuOn5JI=";
}

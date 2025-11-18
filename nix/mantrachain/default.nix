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
  version = "v7.0.0-rc1";
  owner = "mmsqe";
  rev = "3ad5f46686bb885cb6a3907eb3a064ff00bda6dc"; 
  hash = "sha256-Tv/XAwZ4ebdKEcy72bKAyW0Pz7tLj+9HINHIiqag7/s=";
  vendorHash = "sha256-kbM/j1GFbI/1hLpWDBbGwnBQc7B0TjwVv8dPrLSaKAM=";
}

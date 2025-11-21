{
  lib,
  stdenv,
  buildGo123Module,
  fetchFromGitHub,
  fetchurl,
  pkgsStatic,
}:
let
  builder = import ../mantrachain-builder.nix {
    inherit lib stdenv buildGo123Module fetchFromGitHub fetchurl pkgsStatic;
  };
in
builder {
  version = "v7";
  owner = "MANTRA-Chain";
  rev = "97a11bb1cd6c3e5f39676896e655709928972b00";
  hash = "sha256-FrTBgg6EyRhRVnO7DkGp7ejS3YNxxApgtgN0FEze+/s=";
  vendorHash = "sha256-c93BNx/IH3UYd6+14mLrZs0lhCp3v2xiK8grBxSkras=";
}
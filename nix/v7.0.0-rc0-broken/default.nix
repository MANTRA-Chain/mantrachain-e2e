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
  version = "v7.0.0-rc1";
  owner = "mmsqe";
  rev = "586c85ba4d850657c36b3ed161e736228cdfd981"; 
  hash = "sha256-tUggfz+LdxvAw5GNeuEElag4XoX+dj9xQ5cMprCkjdw=";
  vendorHash = "sha256-J9buMhNj0lJhwupgkIYjO0WMiM/v03FpQ2RKH7AoPJ4=";
}

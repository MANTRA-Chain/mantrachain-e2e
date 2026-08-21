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
  version = "v8.3.0";
  owner = "MANTRA-Chain";
  rev = "2ca2afe4ab4bb97de94719faa9d61dbb27634979";
  hash = "sha256-KFqHk7J7cua9Ra7w4kXxMhZsWPkorl5YBSDyBg6mwfo=";
  vendorHash = "sha256-vCcg2vKjNmgPP8GDdvsbIi9tveiAdP4/hmZKp2cwWD0=";
}

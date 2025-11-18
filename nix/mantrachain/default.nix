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
  rev = "822f10b53ae29f338f8bcb92f05fd7408d16466b"; 
  hash = "sha256-/M1h15MZYoLj5tzQqDHgymq+/L1I6EIsuDRkgdMfIUg=";
  vendorHash = "sha256-Q+52fqkBTdBn64KC2vSwbkFkjc9dZ9HKr0oDqxyQZIw=";
}

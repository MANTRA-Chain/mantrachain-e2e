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
  rev = "3698b48b8a1511c37139dd2e31914447f5f1c858";
  hash = "sha256-3/zofwz9n8rTQsEk/A5KhwRWgp/0IqgI7kKcQao+/RM=";
  vendorHash = "sha256-70TdbVc+OB9phw6Z6zlCfd486jZx34GTSdmf7qSobpA=";
}

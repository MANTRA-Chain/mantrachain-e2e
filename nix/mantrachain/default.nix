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
  rev = "a40fd9b02b8c388cd679795bb465e0515752b854";
  hash = "sha256-XPgPNlXFKA2Y7VyhQAmfXVLskMvxx5625sjTFrZTFLU=";
  vendorHash = "sha256-YVXccyjamb6XZySeVGOGxFXXRFBF1H6qyJswrvOmDVg=";
}

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
  rev = "69e7460ffab08f100015862d5e4c7fe66a45da24";
  hash = "sha256-vy/QBm0L4h323kL5AxFxkTqAMbHUWot3KMtLCPAuPdY=";
  vendorHash = "sha256-h26r91LLIqy/xz+sFuvpgNMKMCLcNvQJs53Jmri7dM4=";
}

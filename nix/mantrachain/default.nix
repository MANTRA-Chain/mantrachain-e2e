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
  rev = "7a4ed3ea658f5341cdc0db3d187a39f0ff136aef";
  hash = "sha256-uTyeJkF243tXNe0CCatT4cykWSYCJcJ8WQ6BY1dQA2w=";
  vendorHash = "sha256-KUPjWsP8FIwJrlxnL+1e8gspfDTu8JH2xcNWC1yN6wo=";
}

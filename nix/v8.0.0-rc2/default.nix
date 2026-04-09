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
  version = "v8.0.0-rc2";
  owner = "MANTRA-Chain";
  rev = "5f98fd225ee65a37afa855e6caf5cb0e718e7302";
  hash = "sha256-OQpVpla+0nL5AiA8Ldsp9OOVitOQClV93UQN/bbVDPc=";
  vendorHash = "sha256-h26r91LLIqy/xz+sFuvpgNMKMCLcNvQJs53Jmri7dM4=";
}
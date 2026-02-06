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
  rev = "cd4e9faa80bc0b4026f6068a816ecfa3b9f468f0";
  hash = "sha256-93l3Sf0cGHoG2LK/t4XL88jX6zVIw/GCmdBDdOveJKA=";
  vendorHash = "sha256-eL/vouCkuZsTOXD7OLMeaJJvV0Zk5N4mWz/CGWc9KDo=";
}

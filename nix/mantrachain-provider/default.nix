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
  version = "v7-provider";
  owner = "mmsqe";
  rev = "8b42307b5845965cc3280265d95a715ea3702fbb";
  hash = "sha256-UP9LwfJ741XhjgzQlDhtjWTvKVbskZZqvNSr6nhJTp8=";
  vendorHash = "sha256-9pjYPPb5TyThUXIMctHBvdV0WL7QtCP77+vjPB4fEA0=";
}
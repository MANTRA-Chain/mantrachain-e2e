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
  version = "v7";
  owner = "MANTRA-Chain";
  rev = "99e926740282a341f6e3c3553f5d941a1f3a15aa";
  hash = "sha256-9iNb/q3QwVRyE65SiIvqnksdZbCAmvHJ7YL+m50VChk=";
  vendorHash = "sha256-T2kHD+NBRYoFHzcsUGEjqfWFelhEQKzyKBXrKRfgAKQ=";
}

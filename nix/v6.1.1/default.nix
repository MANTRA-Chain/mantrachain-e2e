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
  version = "v6.1.1";
  owner = "mmsqe";
  rev = "9bf9b6337ab45aa8a5ed87035b4b6c80590e799d";
  hash = "sha256-gqHQgqc2IhuGA2tyjEyjMB8PQyf8jiWGlqaAUFXQcwk=";
  vendorHash = "sha256-25QLzb53iE/ITdc7TRtAsnB3r+RQS5G5rxJh0BnXMDE=";
}
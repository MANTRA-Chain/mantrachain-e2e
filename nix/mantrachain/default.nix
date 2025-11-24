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
  owner = "mmsqe";
  rev = "39607d430f9cbbc5d058f5e5486f3313294e2f39"; 
  hash = "sha256-9G0X1vSQfoGod/uRCwjRqkf0nZnhVFnrvy+3uOVyVPY=";
  vendorHash = "sha256-I3p2lUb/8ZOs5+/jMMnxRZ0MlaSGLRxQJOqwdVtBnjA=";
}

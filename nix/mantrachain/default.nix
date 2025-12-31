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
  rev = "5c7ccb9add0f13bfd2ae963b4d1c183a35653d75";
  hash = "sha256-7qVGmZ7z2lYwWRFPpO3xp6bxaiFKpwze7qRbjFiuVt4=";
  vendorHash = "sha256-rzI3PBpVatgVrLpr4+Q5CS9+61afFsrgFMbfGPW/IFo=";
}

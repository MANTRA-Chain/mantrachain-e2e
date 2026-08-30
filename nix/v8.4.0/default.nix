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
    inherit lib stdenv fetchFromGitHub fetchurl pkgsStatic;
    buildGoModule = buildGo125Module;
    staticBuildGoModule = pkgsStatic.buildGo125Module;
  };
in
builder {
  version = "v8.4.0";
  wasmvmVersion = "v3.0.0";
  rev = "5c08d7bd9e2619952707dae1258d2a30bf024721";
  hash = "sha256-22W5Xit8TPIE6fAQT/TCY+v2jflK8lSvAsRioo9A+eY=";
  vendorHash = "sha256-70TdbVc+OB9phw6Z6zlCfd486jZx34GTSdmf7qSobpA=";
}

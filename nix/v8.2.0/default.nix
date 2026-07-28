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
  version = "v8.2.0";
  owner = "MANTRA-Chain";
  wasmvmVersion = "v3.0.0";
  rev = "23794085904fb54307bce3579c0bd114c75c53ba";
  hash = "sha256-/yaVsAjw3N1KRdjRL0Cab/PnhOH//cWtwMoexwENSso=";
  vendorHash = "sha256-92KVzbNOz1hdneqldGAixzgBSsfLfQ44OsnNc/TJfzI=";
}

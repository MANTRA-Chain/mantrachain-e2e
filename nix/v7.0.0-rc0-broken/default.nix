{
  lib,
  stdenv,
  buildGo123Module,
  fetchFromGitHub,
  fetchurl,
  pkgsStatic,
}:
let
  builder = import ../mantrachain-builder.nix {
    inherit lib stdenv buildGo123Module fetchFromGitHub fetchurl pkgsStatic;
  };
in
builder {
  version = "v7.0.0-rc1";
  owner = "mmsqe";
  rev = "29125ea31603966379b1479ccef49f519c433c1e"; 
  hash = "sha256-DInSYwCfZhXiNPHqkvo2swm3GStsWKMhVysliBRUITw=";
  vendorHash = "sha256-mJ4aRVM0wgtBYmhXJNMHQ6o74p9BzipevTbf3eCxtxQ=";
}

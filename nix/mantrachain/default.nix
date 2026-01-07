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
  rev = "12b28b0f385701df1f04aa9f585a1cbf75753ef0";
  hash = "sha256-X/ZRwaqrF2zZxeD094zDlNXxJYdeh46SitR7nx5YDGs=";
  vendorHash = "sha256-NAlDQt3Bfw2KaQOjLKXqHoPJ9zx1XyXXvr0s7FFGJrc=";
}

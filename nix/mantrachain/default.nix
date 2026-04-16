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
  rev = "31a1e1fce8314d3266f629ed13f015ccf8c19dd6";
  hash = "sha256-mTtNlSNvddVPhMuQxqQluIoK5dNBZ1Ml8mO6OMpY4K0=";
  vendorHash = "sha256-ot9J6FBq32MQjLUbMJYoDrldXnVta7zJxUuhyn0QZwg=";
}

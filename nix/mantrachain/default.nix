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
  version = "v8.1.1";
  owner = "MANTRA-Chain";
  rev = "8330cc2449db43f71cda7fd1259d1f0d652426c5";
  hash = "sha256-eOfSIRp2nZrSO0av9EqUHCH4N1aHF5kMoGjfQoC5qpw=";
  vendorHash = "sha256-Yn8c7H4Ihg6Wr87Xt4geyn+RSceg4t1+2ba9+iFYq18=";
}

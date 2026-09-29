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
  version = "v8.5.0";
  owner = "MANTRA-Chain";
  rev = "68dfcdafdac4c470d48fea7d04864d97887bacf0";
  hash = "sha256-diXDuC+k0UnVyKPA4TZoj4srQHz1w6+ufNFcPxt9Xjw=";
  vendorHash = "sha256-v1g7ppxQB0MOIb+nU3HyTtIfZ7EYCVlAIHB2cpIM6Kc=";
}

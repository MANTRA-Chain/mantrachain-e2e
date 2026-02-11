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
  rev = "5aa769b59d1bfbc6199cf735e71cdf5cd5e74def";
  hash = "sha256-J+/QYtIlKug8mOf4SzsWIO7j5A28Nak/Kcr8ITvy7Q0=";
  vendorHash = "sha256-eL/vouCkuZsTOXD7OLMeaJJvV0Zk5N4mWz/CGWc9KDo=";
}

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
  rev = "1a63d16ec1fa3444fbe694c7aa493ccd7473e92c";
  hash = "sha256-AnZUoKnCKz5e7/defcZ59X+3lHdGmuYgmxJWtHXnGNk=";
  vendorHash = "sha256-eL/vouCkuZsTOXD7OLMeaJJvV0Zk5N4mWz/CGWc9KDo=";
}

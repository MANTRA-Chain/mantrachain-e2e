{ pkgs ? (builtins.getFlake (toString ../..)).legacyPackages.${builtins.currentSystem or "x86_64-linux"} }:
let
  providerMantrachaind = pkgs.mantrachaind_provider;
in
providerMantrachaind
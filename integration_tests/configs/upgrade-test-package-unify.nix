{ pkgs ? import ../../nix { }, includeMantrachaind ? true }:
let
  common = import ./mantrachain-common.nix { inherit pkgs; };
  platform = common.platform;
  versionInfo = common.versionInfo;
  mkMantrachain = common.mkMantrachain;
  releases = {
    genesis = mkMantrachain { version = "v4.0.1"; };
    v5 = pkgs.callPackage ../../nix/unify { };
  };

in
pkgs.linkFarm "upgrade-test-package" (
  pkgs.lib.mapAttrsToList (name: path: { inherit name path; }) releases
)

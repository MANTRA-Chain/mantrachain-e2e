{ pkgs ? import ../../nix { }, includeMantrachaind ? true }:
let
  common = import ./mantrachain-common.nix { inherit pkgs; };
  platform = common.platform;
  releases = {
    genesis = pkgs.callPackage ../../nix/v6.1.1/default.nix {};
    "v7.0.0-rc0" = pkgs.callPackage ../../nix/v7.0.0-rc0/default.nix {};
  } // (
    pkgs.lib.optionalAttrs includeMantrachaind {
      "v7.0.0-rc1" = pkgs.callPackage ../../nix/mantrachain {};
    }
  ) // (
    pkgs.lib.optionalAttrs (!includeMantrachaind) {
      "v7.0.0-rc1" = pkgs.writeShellScriptBin "mantrachaind" ''
        exec mantrachaind "$@"
      '';
    }
  );

in
pkgs.linkFarm "upgrade-test-package" (
  pkgs.lib.mapAttrsToList (name: path: { inherit name path; }) releases
)

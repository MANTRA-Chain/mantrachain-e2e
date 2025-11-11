{ pkgs ? import ../../nix { }, includeMantrachaind ? true }:
let
  common = import ./mantrachain-common.nix { inherit pkgs; };
  v7-rc0 = pkgs.callPackage ../../nix/v7.0.0-rc0/default.nix {
    rev = "v7.0.0-rc0";
  };
  platform = common.platform;
  releases = {
    genesis = common.mkMantrachain { version = "v4.0.1"; };
    "v5.0" = common.mkMantrachain { version = "v5.0.0"; };
    "v6.0.0" = common.mkMantrachain { version = "v6.0.0"; };
    "v6.1.0" = common.mkMantrachain { version = "v6.1.0"; };
    "v7.0.0-rc0" = v7-rc0;
  } // (
    pkgs.lib.optionalAttrs includeMantrachaind {
      "v7.0.0-rc1" = pkgs.callPackage ../../nix/mantrachain { };
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

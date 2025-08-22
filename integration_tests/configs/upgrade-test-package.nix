{ pkgs ? import ../../nix { }, includeMantrachaind ? true }:
let
  common = import ./mantrachain-common.nix { inherit pkgs; };
  platform = common.platform;
  releases = {
    genesis = common.mkMantrachain { version = "v4.0.1"; };
    v5 = common.mkMantrachain { version = "v5.0.0-rc0"; };
    "v5.0.0-rc1" = common.mkMantrachain { version = "v5.0.0-rc1"; };
    "v5.0.0-rc2" = common.mkMantrachain { version = "v5.0.0-rc2"; };
    "v5.0.0-rc3" = common.mkMantrachain { version = "v5.0.0-rc3"; };
    "v5.0.0-rc4" = common.mkMantrachain { version = "v5.0.0-rc4"; };
    "v5.0.0-rc5" = common.mkMantrachain { version = "v5.0.0-rc5"; };
    "v5.0.0-rc6" = common.mkMantrachain { version = "v5.0.0-rc6"; };
  } // (
    pkgs.lib.optionalAttrs includeMantrachaind {
      "v5.0" = pkgs.callPackage ../../nix/mantrachain { };
    }
  ) // (
    pkgs.lib.optionalAttrs (!includeMantrachaind) {
      "v5.0" = pkgs.writeShellScriptBin "mantrachaind" ''
      exec mantrachaind "$@"
    '';
    }
  );

in
pkgs.linkFarm "upgrade-test-package" (
  pkgs.lib.mapAttrsToList (name: path: { inherit name path; }) releases
)

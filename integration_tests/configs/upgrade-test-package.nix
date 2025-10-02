{ pkgs ? import ../../nix { }, includeMantrachaind ? true }:
let
  common = import ./mantrachain-common.nix { inherit pkgs; };
  platform = common.platform;
  releases = {
    genesis = common.mkMantrachain { version = "v4.0.1"; };
    "v5.0.0-rc3" = common.mkMantrachain { version = "v5.0.0-rc3"; };
    "v5.0.0-rc4" = common.mkMantrachain { version = "v5.0.0-rc4"; };
    "v5.0.0-rc5" = common.mkMantrachain { version = "v5.0.0-rc5"; };
    "v5.0.0-rc6" = common.mkMantrachain { version = "v5.0.0-rc6"; };
    "v5.0.0-rc7" = common.mkMantrachain { version = "v5.0.0-rc7"; };
    "v5.0.0-rc8" = common.mkMantrachain { version = "v5.0.0-rc8"; };
    "v5.0" = common.mkMantrachain { version = "v5.0.0"; };
    "v5.0.0-rc9" = common.mkMantrachain { version = "v5.0.0-rc9"; };
  } // (
    pkgs.lib.optionalAttrs includeMantrachaind {
      "v6.0.0-rc0" = pkgs.callPackage ../../nix/mantrachain { };
    }
  ) // (
    pkgs.lib.optionalAttrs (!includeMantrachaind) {
      "v6.0.0-rc0" = pkgs.writeShellScriptBin "mantrachaind" ''
        exec mantrachaind "$@"
      '';
    }
  );

in
pkgs.linkFarm "upgrade-test-package" (
  pkgs.lib.mapAttrsToList (name: path: { inherit name path; }) releases
)

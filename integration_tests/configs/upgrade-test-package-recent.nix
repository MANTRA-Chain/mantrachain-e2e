{ 
  pkgs ? (builtins.getFlake (toString ../..)).legacyPackages.${builtins.currentSystem or "x86_64-linux"}, includeMantrachaind ? true
}:
let
  common = import ./mantrachain-common.nix { inherit pkgs; };
  platform = common.platform;
  releases = {
    genesis = common.mkMantrachain { version = "v5.0.0"; };
    "v6.0.0" = common.mkMantrachain { version = "v6.0.0"; };
    "v7.0.0-rc0" = pkgs.callPackage ../../nix/v7.0.0-rc0-broken/default.nix {};
  };

in
pkgs.linkFarm "upgrade-test-package" (
  pkgs.lib.mapAttrsToList (name: path: { inherit name path; }) releases
)

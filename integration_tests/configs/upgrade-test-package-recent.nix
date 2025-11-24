{ 
  pkgs ? (builtins.getFlake (toString ../..)).legacyPackages.${builtins.currentSystem or "x86_64-linux"},
  useLiteMode ? false
}:
let
  common = import ./mantrachain-common.nix { inherit pkgs; };
  platform = common.platform;
  releases = {
    genesis = pkgs.callPackage ../../nix/v6.1.1/default.nix {};
    "v7.0.0-rc2" = pkgs.callPackage ../../nix/v7.0.0-rc2/default.nix {};
    "v7.0.0-rc2-supply" = if useLiteMode
      then common.localMantrachaindWrapper
      else pkgs.mantrachaind;
  };
  packageName = "upgrade-test-package-recent" + (if useLiteMode then "-lite" else "-full");
in
pkgs.linkFarm packageName (
  pkgs.lib.mapAttrsToList (name: path: { inherit name path; }) releases
)

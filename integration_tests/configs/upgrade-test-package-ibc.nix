{ 
  pkgs ? (builtins.getFlake (toString ../..)).legacyPackages.${builtins.currentSystem or "x86_64-linux"},
  useLiteMode ? false
}:
let
  common = import ./mantrachain-common.nix { inherit pkgs; };
  platform = common.platform;
  releases = {
    genesis = pkgs.callPackage ../../nix/v6.1.3/default.nix {};
    "v7.0.0" = if useLiteMode
      then common.localMantrachaindWrapper
      else pkgs.mantrachaind;
  };
  packageName = "upgrade-test-package-ibc" + (if useLiteMode then "-lite" else "-full");
in
pkgs.linkFarm packageName (
  pkgs.lib.mapAttrsToList (name: path: { inherit name path; }) releases
)

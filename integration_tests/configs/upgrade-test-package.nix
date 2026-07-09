{
  pkgs ? (builtins.getFlake (toString ../..)).legacyPackages.${builtins.currentSystem or "x86_64-linux"},
  useLiteMode ? false
}:
let
  common = import ./mantrachain-common.nix { inherit pkgs; };
  releases = {
    genesis = pkgs.callPackage ../../nix/v8.3.0/default.nix {};
    "v8.4.0" = pkgs.callPackage ../../nix/v8.4.0/default.nix {};
    "v8.5.0" = if useLiteMode
      then common.localMantrachaindWrapper
      else pkgs.mantrachaind;
  };
  packageName = "upgrade-test-package" + (if useLiteMode then "-lite" else "-full");
in
pkgs.linkFarm packageName (
  pkgs.lib.mapAttrsToList (name: path: { inherit name path; }) releases
)

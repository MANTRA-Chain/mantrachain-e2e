{
  pkgs ? (builtins.getFlake (toString ../..)).legacyPackages.${builtins.currentSystem or "x86_64-linux"},
  useLiteMode ? false
}:
let
  common = import ./mantrachain-common.nix { inherit pkgs; };
  releases = {
    genesis = pkgs.callPackage ../../nix/v8.1.1/default.nix {};
    "v8.2.0" = pkgs.callPackage ../../nix/v8.2.0/default.nix {};
    "v8.3.0" = pkgs.callPackage ../../nix/v8.3.0/default.nix {};
    # The ratchet, without which pebble v2 will not open what the releases
    # above leave behind -- and cannot migrate it either.
    "v8.4.0" = pkgs.mantrachaind-pebble-v1;
    # Not an upgrade plan: no state machine changes, so it is a binary swapped
    # in once the ratchet has been everywhere.
    "pebble-v2" = if useLiteMode
      then common.localMantrachaindWrapper
      else pkgs.mantrachaind;
  };
  packageName = "upgrade-test-package" + (if useLiteMode then "-lite" else "-full");
in
pkgs.linkFarm packageName (
  pkgs.lib.mapAttrsToList (name: path: { inherit name path; }) releases
)

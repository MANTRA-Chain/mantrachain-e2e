{ pkgs ? import ../../nix { } }:
let
  baseMantrachaind = pkgs.callPackage ../../nix/mantrachain { };
  brokenMantrachaind = baseMantrachaind.overrideAttrs (oldAttrs: {
    patches = oldAttrs.patches or [ ] ++ [
      ./broken-mantrachaind.patch
    ];
  });
in
brokenMantrachaind

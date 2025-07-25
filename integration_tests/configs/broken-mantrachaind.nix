{
  pkgs ? import ../../nix { },
  includeMantrachaind ? true,
}:
let 
  mantrachaind = (pkgs.callPackage ../../nix/mantrachain/. { });
  brokenMantrachaind = mantrachaind.overrideAttrs (oldAttrs: {
    patches = oldAttrs.patches or [ ] ++ [
      ./broken-mantrachaind.patch
    ];
  });
in
if includeMantrachaind then brokenMantrachaind else mantrachaind
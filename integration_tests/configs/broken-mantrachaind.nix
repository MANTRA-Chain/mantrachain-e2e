{
  pkgs ? import ../../nix { },
  includeMainMantrachaind ? true,
}:
let 
  baseMantrachaind = if includeMainMantrachaind 
    then (pkgs.callPackage ../../nix/main/. { })
    else (pkgs.callPackage ../../nix/mantrachain/. { });
  
  brokenMantrachaind = baseMantrachaind.overrideAttrs (oldAttrs: {
    patches = oldAttrs.patches or [ ] ++ [
      ./broken-mantrachaind.patch
    ];
  });
in
brokenMantrachaind

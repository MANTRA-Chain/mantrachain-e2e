{ pkgs ? (builtins.getFlake (toString ../..)).legacyPackages.${builtins.currentSystem or "x86_64-linux"} }:
let
  baseMantrachaind = pkgs.mantrachaind;
  brokenMantrachaind = baseMantrachaind.overrideAttrs (oldAttrs: {
    patches = oldAttrs.patches or [ ] ++ [
      ./broken-mantrachaind.patch
    ];
  });
in
brokenMantrachaind
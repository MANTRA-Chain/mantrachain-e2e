{
  sources ? import ./sources.nix,
  system ? builtins.currentSystem,
  ...
}:
import sources.nixpkgs {
  overlays = [
    (_: pkgs: {
      flake-compat = import sources.flake-compat;
      go-ethereum = pkgs.callPackage ./go-ethereum.nix {
        inherit (pkgs.darwin) libobjc;
        inherit (pkgs.darwin.apple_sdk.frameworks) IOKit;
      };
      dapp = pkgs.dapp;
    })
    (import "${sources.poetry2nix}/overlay.nix")
    (pkgs: _:
      import ./scripts.nix {
        inherit pkgs;
        config = {
          geth-genesis = ../scripts/geth-genesis.json;
          dotenv = builtins.path { name = "dotenv"; path = ../scripts/.env; };
        };
      })
    (_: pkgs: { hermes = pkgs.callPackage ./hermes.nix { src = sources.hermes; };})
    (_: pkgs: { test-env = pkgs.callPackage ./testenv.nix { }; })
    (_: pkgs: { cosmovisor = pkgs.callPackage ./cosmovisor.nix { }; })
    (_: pkgs: { mantrachaind = pkgs.callPackage ./mantrachain/default.nix { }; })
  ];
  config = { };
  inherit system;
}

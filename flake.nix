{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/release-25.05";
    flake-utils.url = "github:numtide/flake-utils";
    flake-compat.url = "github:edolstra/flake-compat";
    poetry2nix = {
      url = "github:nix-community/poetry2nix";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.flake-utils.follows = "flake-utils";
    };
    hermes-src = {
      url = "github:mmsqe/ibc-rs/ae80ab348952840696e6c9a0c7096d2de11ea579";
      flake = false;
    };
  };

  outputs = { self, nixpkgs, flake-compat, poetry2nix, hermes-src, flake-utils, ... }:
    let
      overlays =
        [
          (_: pkgs: {
            flake-compat = flake-compat;
            go-ethereum = pkgs.callPackage ./nix/go-ethereum.nix {
              inherit (pkgs.darwin) libobjc;
              inherit (pkgs.darwin.apple_sdk.frameworks) IOKit;
            };
            dapp = pkgs.dapp;
          })
          (import "${poetry2nix}/overlay.nix")
          (_: pkgs: {
            hermes = pkgs.callPackage ./nix/hermes.nix { src = hermes-src; };
          })
          (_: pkgs: { cosmovisor = pkgs.callPackage ./nix/cosmovisor.nix { }; })
          (_: pkgs: { mantrachaind = pkgs.callPackage ./nix/mantrachain/default.nix { }; })
          (_: pkgs: {
            evmd = pkgs.callPackage ./nix/evm/default.nix { };
          })
        ];
      forAllSystems = nixpkgs.lib.genAttrs nixpkgs.lib.systems.flakeExposed;
    in
    {
      overlays.default = overlays;

      legacyPackages = forAllSystems (system:
        import nixpkgs {
          inherit system;
          overlays = overlays;
          config = { };
        }
      );

      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs {
            inherit system;
            overlays = overlays;
            config = { };
          };
        in {
          default = pkgs.mantrachaind;
          mantrachaind = pkgs.mantrachaind;
          evmd = pkgs.evmd;
          hermes = pkgs.hermes;
          cosmovisor = pkgs.cosmovisor;
          go-ethereum = pkgs.go-ethereum;
        }
      );

      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs {
            inherit system;
            overlays = overlays;
            config = { };
          };

          scripts = import ./nix/scripts.nix {
            inherit pkgs;
            config = {
              geth-genesis = ./scripts/geth-genesis.json;
              dotenv = toString ./scripts/.env;
            };
          };

        in {
          default = pkgs.mkShell {
            buildInputs =
              [
                pkgs.nixfmt-rfc-style
                pkgs.solc
                pkgs.python312
                pkgs.python312Packages.jsonnet
                pkgs.uv
                pkgs.direnv
                pkgs.git
                pkgs.hermes
                pkgs.go-ethereum
                pkgs.evmd
                pkgs.cosmovisor
                scripts.start-scripts
                pkgs.mantrachaind
              ];
            
            shellHook = ''
              export PATH=${pkgs.go-ethereum}/bin:$PATH
            '';
          };
        }
      );
    };
}

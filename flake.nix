{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/release-25.05";
    flake-utils.url = "github:numtide/flake-utils";
    flake-compat.url = "github:edolstra/flake-compat";
    hermes-src = {
      url = "github:mmsqe/ibc-rs/ae80ab348952840696e6c9a0c7096d2de11ea579";
      flake = false;
    };
  };

  outputs = { self, nixpkgs, flake-compat, hermes-src, flake-utils, ... }:
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
            solc_0_8_21 = pkgs.callPackage ./nix/solc.nix { };
          })
          (_: pkgs: {
            hermes = pkgs.callPackage ./nix/hermes.nix { src = hermes-src; };
          })
          (_: pkgs: { cosmovisor = pkgs.callPackage ./nix/cosmovisor.nix { }; })
          (_: pkgs: { mantrachaind = pkgs.callPackage ./nix/mantrachain/default.nix { }; })
          (_: pkgs: { evmd = pkgs.callPackage ./nix/evm/default.nix { }; })
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

          cprotobuf = pkgs.python312Packages.buildPythonPackage {
            pname = "cprotobuf";
            version = "0.1.12";
            src = pkgs.fetchPypi {
              pname = "cprotobuf";
              version = "0.1.12";
              hash = "sha256-YX2X0TAMobIIE3e7o9mSSZIH5VTKf+rBOmxrqdKFtBg=";
            };
            nativeBuildInputs = [ pkgs.python312Packages.cython ];
            doCheck = false;
          };

          benchmark-testcase = pkgs.python312Packages.buildPythonApplication {
            pname = "benchmark-testcase";
            version = "0.1.0";
            format = "pyproject";
            src = ./integration_tests;
            nativeBuildInputs = [ pkgs.python312Packages.hatchling ];
            propagatedBuildInputs = with pkgs.python312Packages; [
              click
              aiohttp
              backoff
              eth-abi
              ujson
              hexbytes
              tomlkit
              web3
              jsonmerge
              requests
              cprotobuf
              bech32
              pydantic
              eth-utils
              eth-hash
            ];
            # skip dependency check - only need deps for stateless-testcase cli
            dontCheckRuntimeDeps = true;
          };

          testground-image = pkgs.callPackage ./nix/testground-image.nix {
            inherit benchmark-testcase;
            chaind = pkgs.mantrachaind;
            imageName = "mantra-testground";
          };

          testground-image-evmd = pkgs.callPackage ./nix/testground-image.nix {
            inherit benchmark-testcase;
            chaind = pkgs.evmd;
            imageName = "evmd-testground";
          };
        in {
          default = pkgs.mantrachaind;
          mantrachaind = pkgs.mantrachaind;
          evmd = pkgs.evmd;
          hermes = pkgs.hermes;
          cosmovisor = pkgs.cosmovisor;
          go-ethereum = pkgs.go-ethereum;
          inherit benchmark-testcase testground-image testground-image-evmd;
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

          commonInputs = [
            pkgs.nixfmt-rfc-style
            pkgs.solc_0_8_21
            pkgs.python312
            pkgs.python312Packages.jsonnet
            pkgs.uv
            pkgs.direnv
            pkgs.git
            pkgs.hermes
            pkgs.go-ethereum
            pkgs.cosmovisor
            pkgs.rustc
            pkgs.cargo
            scripts.start-scripts
            pkgs.foundry
          ];

          commonShellHook = ''
            export PATH=${pkgs.go-ethereum}/bin:$PATH
            if [ -d integration_tests/.venv ]; then
              source integration_tests/.venv/bin/activate
            fi
          '';

        in {
          default = pkgs.mkShell {
            buildInputs = commonInputs ++ [ pkgs.mantrachaind pkgs.evmd ];
            shellHook = commonShellHook;
          };

          lite = pkgs.mkShell {
            buildInputs = commonInputs ++ [ pkgs.evmd ];
            shellHook = commonShellHook;
          };

          lite_evmd = pkgs.mkShell {
            buildInputs = commonInputs;
            shellHook = commonShellHook;
          };
        }
      );
    };
}

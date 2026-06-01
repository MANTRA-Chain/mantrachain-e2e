{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    flake-compat.url = "github:edolstra/flake-compat";
    hermes-src = {
      url = "github:mmsqe/ibc-rs/ae80ab348952840696e6c9a0c7096d2de11ea579";
      flake = false;
    };
    eureka-relayer-src = {
      # ghcr.io/cosmos/eureka-relayer:pr-952 is built from this commit.
      url = "github:cosmos/solidity-ibc-eureka/d1fdeda051c63bd3cace02ab73171f835f9d09a8";
      flake = false;
    };
    ibc-attestor-src = {
      url = "github:mmsqe/ibc-attestor/a2f43d7b5067c1ee29e4b8978bbc39840fccc06e";
      flake = false;
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-compat,
      hermes-src,
      eureka-relayer-src,
      ibc-attestor-src,
      flake-utils,
      ...
    }:
    let
      overlays = [
        (_: pkgs: {
          flake-compat = flake-compat;
          go-ethereum = pkgs.callPackage ./nix/go-ethereum.nix { };
          dapp = pkgs.dapp;
          solc_0_8_21 = pkgs.callPackage ./nix/solc.nix { };
        })
        (_: pkgs: {
          hermes = pkgs.callPackage ./nix/hermes.nix { src = hermes-src; };
        })
        (_: pkgs: {
          eureka-relayer = pkgs.callPackage ./nix/eureka-relayer.nix {
            src = eureka-relayer-src;
          };
        })
        (_: pkgs: {
          ibc-attestor = pkgs.callPackage ./nix/ibc-attestor.nix {
            src = ibc-attestor-src;
          };
        })
        (_: pkgs: {
          # SP1 ICS07 light-client testing: operator (genesis + fixtures) built
          # from the same relayer source, plus vendored prebuilt program ELFs.
          sp1-operator = pkgs.callPackage ./nix/sp1-operator.nix {
            src = eureka-relayer-src;
          };
          sp1-ics07-programs = pkgs.callPackage ./nix/sp1-ics07-programs.nix { };
        })
        (_: pkgs: { cosmovisor = pkgs.callPackage ./nix/cosmovisor.nix { }; })
        (_: pkgs: { mantrachaind = pkgs.callPackage ./nix/mantrachain/default.nix { }; })
        (_: pkgs: { evmd = pkgs.callPackage ./nix/evm/default.nix { }; })
      ];
      forAllSystems = nixpkgs.lib.genAttrs nixpkgs.lib.systems.flakeExposed;
    in
    {
      overlays.default = overlays;

      legacyPackages = forAllSystems (
        system:
        import nixpkgs {
          inherit system;
          overlays = overlays;
          config = { };
        }
      );

      packages = forAllSystems (
        system:
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
            pyproject = true;
            build-system = with pkgs.python312Packages; [
              setuptools
              wheel
              cython
            ];
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
        in
        {
          default = pkgs.mantrachaind;
          mantrachaind = pkgs.mantrachaind;
          evmd = pkgs.evmd;
          hermes = pkgs.hermes;
          eureka-relayer = pkgs.eureka-relayer;
          ibc-attestor = pkgs.ibc-attestor;
          sp1-operator = pkgs.sp1-operator;
          sp1-ics07-programs = pkgs.sp1-ics07-programs;
          cosmovisor = pkgs.cosmovisor;
          go-ethereum = pkgs.go-ethereum;
          inherit benchmark-testcase testground-image testground-image-evmd;
        }
      );

      devShells = forAllSystems (
        system:
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
            pkgs.eureka-relayer
            pkgs.ibc-attestor
            pkgs.sp1-operator
            pkgs.sp1-ics07-programs
            pkgs.go-ethereum
            pkgs.cosmovisor
            pkgs.rustc
            pkgs.cargo
            scripts.start-scripts
          ];

          commonShellHook = ''
            export PATH=${pkgs.go-ethereum}/bin:$PATH
            # Vendored SP1 ICS07 program ELFs, consumed by the SP1 e2e
            # (eureka_deploy_sp1._elf_paths + the relayer sp1_programs config).
            export SP1_ICS07_PROGRAMS_DIR=${pkgs.sp1-ics07-programs}
            if [ -d integration_tests/.venv ]; then
              source integration_tests/.venv/bin/activate
            fi
          '';

        in
        {
          default = pkgs.mkShell {
            buildInputs = commonInputs ++ [
              pkgs.mantrachaind
              pkgs.evmd
            ];
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

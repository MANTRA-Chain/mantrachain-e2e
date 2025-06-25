{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/release-24.11";
    flake-utils.url = "github:numtide/flake-utils";
    poetry2nix = {
      url = "github:nix-community/poetry2nix";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.flake-utils.follows = "flake-utils";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      poetry2nix,
    }:
    (flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs {
          inherit system;
          overlays = self.overlays.default;
          config = { };
        };
      in
      rec {
        legacyPackages = pkgs;
        packages.default = pkgs.mantrachain;
        devShells = rec {
          default = pkgs.mkShell {
            buildInputs = [
              packages.default.go
              pkgs.nixfmt-rfc-style
            ];
          };
          full = pkgs.mkShell { buildInputs = default.buildInputs ++ [ pkgs.test-env ]; };
        };
      }
    ))
    // {
      overlays.default = [
        poetry2nix.overlays.default
        (final: super: {
          # go = super.go_1_23;
          test-env = final.callPackage ./nix/testenv.nix { };
          mantrachain = final.callPackage ./nix/mantrachain { };
        })
      ];
    };
}

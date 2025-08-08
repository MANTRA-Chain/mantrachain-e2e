let
  pkgs = import ../../nix { };

  platform =
    if pkgs.stdenv.isDarwin then "darwin-amd64"
    else if pkgs.stdenv.isLinux && pkgs.stdenv.hostPlatform.isAarch64 then "linux-arm64"
    else if pkgs.stdenv.isLinux && pkgs.stdenv.hostPlatform.isx86_64 then "linux-amd64"
    else throw "Unsupported platform";

  versionInfo = {
    "v4.0.1" = {
      filename = "mantrachaind-4.0.1-${platform}.tar.gz";
      sha256 = {
        darwin-amd64 = "sha256-mOpp9el+akznUyPgoZSA4j7RRlTtKpFJjH16JZew5+8=";
        linux-arm64 = "sha256-gExKEcM9CyUimbuBSCz2YL7YuiFyBUmf3hbYJVfB7XQ=";
        linux-amd64 = "sha256-gExKEcM9CyUimbuBSCz2YL7YuiFyBUmf3hbYJVfB7XQ=";
      };
    };
    "v5.0.0-rc0" = {
      filename = "mantrachaind-5.0.0-rc0-${platform}.tar.gz";
      sha256 = {
        darwin-amd64 = "sha256-FyUgtoQVwsO2q3/3uZ6D+TeVR3DCmqBEubveXtzLkEo=";
        linux-arm64 = "sha256-sSXFN2gHWLUb6wn0No9r23ty6bOta2iebrwBnAyGRyM=";
        linux-amd64 = "sha256-sSXFN2gHWLUb6wn0No9r23ty6bOta2iebrwBnAyGRyM=";
      };
    };
    "v5.0.0-rc1" = {
      filename = "mantrachaind-5.0.0-rc1-${platform}.tar.gz";
      sha256 = {
        darwin-amd64 = "sha256-G4JcV4VbKWleGaVlVKkNalbPF6Uoxkv4nsLlCW8nZkE=";
        linux-arm64 = "sha256-5m9+fmA+/80SAYwwb9wgB1K5yz3nXcrc2OlYNMmdE/M=";
        linux-amd64 = "sha256-5m9+fmA+/80SAYwwb9wgB1K5yz3nXcrc2OlYNMmdE/M=";
      };
    };
    "v5.0.0-rc2" = {
      filename = "mantrachaind-5.0.0-rc2-${platform}.tar.gz";
      sha256 = {
        darwin-amd64 = "sha256-wiJscoijqIrWb8AMALzj13YN54y62997fXqU8g3BjX0=";
        linux-arm64 = "sha256-7FqreDBr85vgjCEr8WyCqOoG0Y9SbrVjVF3LCJuMoxw=";
        linux-amd64 = "sha256-7FqreDBr85vgjCEr8WyCqOoG0Y9SbrVjVF3LCJuMoxw=";
      };
    };
    "v5.0.0-rc3" = {
      filename = "mantrachaind-5.0.0-rc3-${platform}.tar.gz";
      sha256 = {
        darwin-amd64 = "sha256-aR/eo296lnN2C6RkRlqAP79gVN7nPdM+ad/RTeSFOx0=";
        linux-arm64 = "sha256-+n212FGcXI7TaBfdF1GyLsYe2Vz48GJ6Pm99K1ffDnc=";
        linux-amd64 = "sha256-+n212FGcXI7TaBfdF1GyLsYe2Vz48GJ6Pm99K1ffDnc=";
      };
    };
  };

  mkMantrachain = { version, name ? "mantrachaind-${version}" }: 
    let info = versionInfo.${version};
    in pkgs.stdenv.mkDerivation {
      inherit name;
      src = pkgs.fetchurl {
        url = "https://github.com/MANTRA-Chain/mantrachain/releases/download/${version}/${info.filename}";
        sha256 = info.sha256.${platform};
      };
      unpackPhase = "tar xzf $src";
      installPhase = ''
        mkdir -p $out/bin
        cp mantrachaind $out/bin/
      '';
    };

  releases = {
    genesis = mkMantrachain { version = "v4.0.1"; };
    v5 = mkMantrachain { version = "v5.0.0-rc0"; };
    "v5.0.0-rc1" = mkMantrachain { version = "v5.0.0-rc1"; };
    "v5.0.0-rc2" = mkMantrachain { version = "v5.0.0-rc2"; };
    "v5.0.0-rc3" = mkMantrachain { version = "v5.0.0-rc3"; };
    "v5.0.0-rc4" = pkgs.callPackage ../../nix/mantrachain { };
  };

in
pkgs.linkFarm "upgrade-test-package" (
  pkgs.lib.mapAttrsToList (name: path: { inherit name path; }) releases
)

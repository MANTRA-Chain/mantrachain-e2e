let
  pkgs = import ../../nix { };

  platform =
    if pkgs.stdenv.isDarwin then "darwin-amd64"
    else if pkgs.stdenv.isLinux && pkgs.stdenv.hostPlatform.isAarch64 then "linux-arm64"
    else if pkgs.stdenv.isLinux && pkgs.stdenv.hostPlatform.isx86_64 then "linux-amd64"
    else throw "Unsupported platform";

  genesisSha256 =
    if pkgs.stdenv.isDarwin then "sha256-mOpp9el+akznUyPgoZSA4j7RRlTtKpFJjH16JZew5+8="
    else if pkgs.stdenv.isLinux && pkgs.stdenv.hostPlatform.isAarch64 then "sha256-gExKEcM9CyUimbuBSCz2YL7YuiFyBUmf3hbYJVfB7XQ="
    else if pkgs.stdenv.isLinux && pkgs.stdenv.hostPlatform.isx86_64 then "sha256-gExKEcM9CyUimbuBSCz2YL7YuiFyBUmf3hbYJVfB7XQ="
    else throw "Unsupported platform";
  releasedSha256 =
    if pkgs.stdenv.isDarwin then "sha256-FyUgtoQVwsO2q3/3uZ6D+TeVR3DCmqBEubveXtzLkEo="
    else if pkgs.stdenv.isLinux && pkgs.stdenv.hostPlatform.isAarch64 then "sha256-sSXFN2gHWLUb6wn0No9r23ty6bOta2iebrwBnAyGRyM="
    else if pkgs.stdenv.isLinux && pkgs.stdenv.hostPlatform.isx86_64 then "sha256-sSXFN2gHWLUb6wn0No9r23ty6bOta2iebrwBnAyGRyM="
    else throw "Unsupported platform";

  genesisUrl = "https://github.com/MANTRA-Chain/mantrachain/releases/download/v4.0.1/mantrachaind-4.0.1-${platform}.tar.gz";
  releasedUrl = "https://github.com/MANTRA-Chain/mantrachain/releases/download/v5.0.0-rc0/mantrachaind-5.0.0-rc0-${platform}.tar.gz";

  genesis = pkgs.stdenv.mkDerivation {
    name = "mantrachaind-v4.0.1";
    src = pkgs.fetchurl {
      url = genesisUrl;
      sha256 = genesisSha256;
    };
    unpackPhase = "tar xzf $src";
    installPhase = ''
      mkdir -p $out
      mkdir -p $out/bin
      cp mantrachaind $out/bin/
    '';
  };

  released = pkgs.stdenv.mkDerivation {
    name = "mantrachaind-v5.0.0-rc0";
    src = pkgs.fetchurl {
      url = releasedUrl;
      sha256 = releasedSha256;
    };
    unpackPhase = "tar xzf $src";
    installPhase = ''
      mkdir -p $out
      mkdir -p $out/bin
      cp mantrachaind $out/bin/
    '';
  };

in
pkgs.linkFarm "upgrade-test-package" [
  {
    name = "genesis";
    path = genesis;
  }
  {
    name = "v5";
    path = released;
  }
]

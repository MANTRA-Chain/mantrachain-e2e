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
  releasedV5Rc0Sha256 =
    if pkgs.stdenv.isDarwin then "sha256-FyUgtoQVwsO2q3/3uZ6D+TeVR3DCmqBEubveXtzLkEo="
    else if pkgs.stdenv.isLinux && pkgs.stdenv.hostPlatform.isAarch64 then "sha256-sSXFN2gHWLUb6wn0No9r23ty6bOta2iebrwBnAyGRyM="
    else if pkgs.stdenv.isLinux && pkgs.stdenv.hostPlatform.isx86_64 then "sha256-sSXFN2gHWLUb6wn0No9r23ty6bOta2iebrwBnAyGRyM="
    else throw "Unsupported platform";
  releasedV5Rc1Sha256 =
    if pkgs.stdenv.isDarwin then "sha256-G4JcV4VbKWleGaVlVKkNalbPF6Uoxkv4nsLlCW8nZkE="
    else if pkgs.stdenv.isLinux && pkgs.stdenv.hostPlatform.isAarch64 then "sha256-5m9+fmA+/80SAYwwb9wgB1K5yz3nXcrc2OlYNMmdE/M="
    else if pkgs.stdenv.isLinux && pkgs.stdenv.hostPlatform.isx86_64 then "sha256-5m9+fmA+/80SAYwwb9wgB1K5yz3nXcrc2OlYNMmdE/M="
    else throw "Unsupported platform";
  releasedV5Rc2Sha256 =
    if pkgs.stdenv.isDarwin then "sha256-wiJscoijqIrWb8AMALzj13YN54y62997fXqU8g3BjX0="
    else if pkgs.stdenv.isLinux && pkgs.stdenv.hostPlatform.isAarch64 then "sha256-7FqreDBr85vgjCEr8WyCqOoG0Y9SbrVjVF3LCJuMoxw="
    else if pkgs.stdenv.isLinux && pkgs.stdenv.hostPlatform.isx86_64 then "sha256-7FqreDBr85vgjCEr8WyCqOoG0Y9SbrVjVF3LCJuMoxw="
    else throw "Unsupported platform";
  releasedV5Rc3Sha256 =
    if pkgs.stdenv.isDarwin then ""
    else if pkgs.stdenv.isLinux && pkgs.stdenv.hostPlatform.isAarch64 then ""
    else if pkgs.stdenv.isLinux && pkgs.stdenv.hostPlatform.isx86_64 then ""
    else throw "Unsupported platform";

  genesisUrl = "https://github.com/MANTRA-Chain/mantrachain/releases/download/v4.0.1/mantrachaind-4.0.1-${platform}.tar.gz";
  releasedV5Rc0Url = "https://github.com/MANTRA-Chain/mantrachain/releases/download/v5.0.0-rc0/mantrachaind-5.0.0-rc0-${platform}.tar.gz";
  releasedV5Rc1Url = "https://github.com/MANTRA-Chain/mantrachain/releases/download/v5.0.0-rc1/mantrachaind-5.0.0-rc1-${platform}.tar.gz";
  releasedV5Rc2Url = "https://github.com/MANTRA-Chain/mantrachain/releases/download/v5.0.0-rc2/mantrachaind-5.0.0-rc2-${platform}.tar.gz";
  releasedV5Rc3Url = "https://github.com/MANTRA-Chain/mantrachain/releases/download/v5.0.0-rc3/mantrachaind-5.0.0-rc3-${platform}.tar.gz";

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

  releasedV5Rc0 = pkgs.stdenv.mkDerivation {
    name = "mantrachaind-v5.0.0-rc0";
    src = pkgs.fetchurl {
      url = releasedV5Rc0Url;
      sha256 = releasedV5Rc0Sha256;
    };
    unpackPhase = "tar xzf $src";
    installPhase = ''
      mkdir -p $out
      mkdir -p $out/bin
      cp mantrachaind $out/bin/
    '';
  };

  releasedV5Rc1 = pkgs.stdenv.mkDerivation {
    name = "mantrachaind-v5.0.0-rc1";
    src = pkgs.fetchurl {
      url = releasedV5Rc1Url;
      sha256 = releasedV5Rc1Sha256;
    };
    unpackPhase = "tar xzf $src";
    installPhase = ''
      mkdir -p $out
      mkdir -p $out/bin
      cp mantrachaind $out/bin/
    '';
  };

  releasedV5Rc2 = pkgs.stdenv.mkDerivation {
    name = "mantrachaind-v5.0.0-rc2";
    src = pkgs.fetchurl {
      url = releasedV5Rc2Url;
      sha256 = releasedV5Rc2Sha256;
    };
    unpackPhase = "tar xzf $src";
    installPhase = ''
      mkdir -p $out
      mkdir -p $out/bin
      cp mantrachaind $out/bin/
    '';
  };

  releasedV5Rc3 = pkgs.stdenv.mkDerivation {
    name = "mantrachaind-v5.0.0-rc3";
    src = pkgs.fetchurl {
      url = releasedV5Rc3Url;
      sha256 = releasedV5Rc3Sha256;
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
    path = releasedV5Rc0;
  }
  {
    name = "v5.0.0-rc1";
    path = releasedV5Rc1;
  }
  {
    name = "v5.0.0-rc2";
    path = releasedV5Rc2;
  }
  {
    name = "v5.0.0-rc3";
    path = releasedV5Rc3;
  }
]

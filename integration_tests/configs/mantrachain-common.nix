{ pkgs }:
let
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
    "v5.0.0-rc4" = {
      filename = "mantrachaind-5.0.0-rc4-${platform}.tar.gz";
      sha256 = {
        darwin-amd64 = "sha256-Tj0XrC/ncGnO0jK2f13TFPO11UxndSKqMe/9iNXJy34=";
        linux-arm64 = "sha256-z98DR0hYLyR5HfzyMZREiYMS8eq0/8rrQjB53/KHnSQ=";
        linux-amd64 = "sha256-z98DR0hYLyR5HfzyMZREiYMS8eq0/8rrQjB53/KHnSQ=";
      };
    };
    "v5.0.0-rc5" = {
      filename = "mantrachaind-5.0.0-rc5-${platform}.tar.gz";
      sha256 = {
        darwin-amd64 = "sha256-1UsVHyUlV7I5Lp4pefbVUjlOoRh6czEqRwzxPZR8FrM=";
        linux-arm64 = "sha256-TonsORkOBzi5CgAZ3seDTlvhquLw9UvNfp3q1kMW4EE=";
        linux-amd64 = "sha256-TonsORkOBzi5CgAZ3seDTlvhquLw9UvNfp3q1kMW4EE=";
      };
    };
    "v5.0.0-rc6" = {
      filename = "mantrachaind-5.0.0-rc6-${platform}.tar.gz";
      sha256 = {
        darwin-amd64 = "sha256-bXIZx9aF1+i1POq0Ah6UX4wgcsznXiQseF2jxdxK70U=";
        linux-arm64 = "sha256-pxRSgZrQx/2brjpGZ1KmwBWN4dA5XjNXTbYm8jAedh8=";
        linux-amd64 = "sha256-pxRSgZrQx/2brjpGZ1KmwBWN4dA5XjNXTbYm8jAedh8=";
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
in
{
  platform = platform;
  versionInfo = versionInfo;
  mkMantrachain = mkMantrachain;
}

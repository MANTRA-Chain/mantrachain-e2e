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
    "v5.0.0-rc7" = {
      filename = "mantrachaind-5.0.0-rc7-${platform}.tar.gz";
      sha256 = {
        darwin-amd64 = "sha256-/w2UvwAjipuBLKJzswqNR1zti7L4wxvog5wVr2Hv57Y=";
        linux-arm64 = "sha256-5JoSVg9FGkbuMTlEQsvllIPyIZwaDGzzog5JJxr/6IY=";
        linux-amd64 = "sha256-5JoSVg9FGkbuMTlEQsvllIPyIZwaDGzzog5JJxr/6IY=";
      };
    };
    "v5.0.0-rc8" = {
      filename = "mantrachaind-5.0.0-rc8-${platform}.tar.gz";
      sha256 = {
        darwin-amd64 = "sha256-Pz8hum/wPHTnIBxN+xxdluEsfEKtFMeY2NaJa7Bwzg4=";
        linux-arm64 = "sha256-wYd+I+qfZNRrwiTy3wGnC/W8Zt+AUD5nsXy9habkzy8=";
        linux-amd64 = "sha256-wYd+I+qfZNRrwiTy3wGnC/W8Zt+AUD5nsXy9habkzy8=";
      };
    };
    "v5.0.0-rc9" = {
      filename = "mantrachaind-5.0.0-rc9-${platform}.tar.gz";
      sha256 = {
        darwin-amd64 = "sha256-87ZFkqmSbI5RcVvSMAKOCc72hzrbgDKtlC/vG4Tq9XI=";
        linux-arm64 = "sha256-JPYm3zjf+5wDVydhglDfXrlCm9apCXIfUsfQ4O7jfhw=";
        linux-amd64 = "sha256-JPYm3zjf+5wDVydhglDfXrlCm9apCXIfUsfQ4O7jfhw=";
      };
    };
    "v5.0.0" = {
      filename = "mantrachaind-5.0.0-${platform}.tar.gz";
      sha256 = {
        darwin-amd64 = "sha256-PUXb9BG6/Dao7fvC0btOtPJhGAMDi74P6sG7zkkzKQY=";
        linux-arm64 = "sha256-2kyy5wegogsWHD4ntI+oFxTTu0ATq2iLPxJ8ahUjejY=";
        linux-amd64 = "sha256-2kyy5wegogsWHD4ntI+oFxTTu0ATq2iLPxJ8ahUjejY=";
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

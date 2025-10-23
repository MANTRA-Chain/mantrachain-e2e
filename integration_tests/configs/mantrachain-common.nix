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
    "v5.0.0" = {
      filename = "mantrachaind-5.0.0-${platform}.tar.gz";
      sha256 = {
        darwin-amd64 = "sha256-PUXb9BG6/Dao7fvC0btOtPJhGAMDi74P6sG7zkkzKQY=";
        linux-arm64 = "sha256-2kyy5wegogsWHD4ntI+oFxTTu0ATq2iLPxJ8ahUjejY=";
        linux-amd64 = "sha256-2kyy5wegogsWHD4ntI+oFxTTu0ATq2iLPxJ8ahUjejY=";
      };
    };
    "v6.0.0" = {
      filename = "mantrachaind-6.0.0-${platform}.tar.gz";
      sha256 = {
        darwin-amd64 = "sha256-pNKlTiN/JgEL/2ZFuc0YJGLKWaem4xMIm6H/7PRByOc=";
        linux-arm64 = "sha256-BOQFMjDk/aTqjr285/ipbWxQRps+l2Kq9Xn/sklICcY=";
        linux-amd64 = "sha256-BOQFMjDk/aTqjr285/ipbWxQRps+l2Kq9Xn/sklICcY=";
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

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
    "v6.1.0" = {
      filename = "mantrachaind-6.1.0-${platform}.tar.gz";
      sha256 = {
        darwin-amd64 = "sha256-nSeUd146p3ImWim+9ZTW0VJ+1tKeNU8jkf4aJ2+szms=";
        linux-arm64 = "sha256-pFzbh7KUjM1UpvdpLQkReWTHwoBelKe3f4gjv2fcJrE=";
        linux-amd64 = "sha256-pFzbh7KUjM1UpvdpLQkReWTHwoBelKe3f4gjv2fcJrE=";
      };
    };
    "v7.0.0-rc2" = {
      filename = "mantrachaind-7.0.0-rc2-${platform}.tar.gz";
      sha256 = {
        darwin-amd64 = "sha256-1uzvEuQ0gb67QJaWtmHDpU/BVdy2u7UcA1AF0NV3+m0=";
        linux-arm64 = "sha256-s3W9BdooUaELs6efHHWb80OlKWa2QV3CWM8NJ1jN4R0=";
        linux-amd64 = "sha256-s3W9BdooUaELs6efHHWb80OlKWa2QV3CWM8NJ1jN4R0=";
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

  localMantrachaindWrapper = pkgs.writeShellScriptBin "mantrachaind" ''
    WRAPPER_DIR="$(dirname "$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")")"
    REAL_MANTRACHAIND=""
    IFS=':' read -ra PATH_ARRAY <<< "$PATH"
    for dir in "''${PATH_ARRAY[@]}"; do
      if [ "$dir" != "$WRAPPER_DIR" ] && [ -x "$dir/mantrachaind" ]; then
        REAL_MANTRACHAIND="$dir/mantrachaind"
        break
      fi
    done
    if [ -z "$REAL_MANTRACHAIND" ] || [ ! -x "$REAL_MANTRACHAIND" ]; then
      echo "Error: mantrachaind not found in PATH" >&2
      exit 1
    fi
    exec "$REAL_MANTRACHAIND" "$@"
  '';
in
{
  platform = platform;
  versionInfo = versionInfo;
  mkMantrachain = mkMantrachain;
  localMantrachaindWrapper = localMantrachaindWrapper;
}

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
    "v5" = pkgs.callPackage ../../nix/unify { };
  };

in
pkgs.linkFarm "upgrade-test-package" (
  pkgs.lib.mapAttrsToList (name: path: { inherit name path; }) releases
)

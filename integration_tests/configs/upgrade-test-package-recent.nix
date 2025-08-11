let
  pkgs = import ../../nix { };

  platform =
    if pkgs.stdenv.isDarwin then "darwin-amd64"
    else if pkgs.stdenv.isLinux && pkgs.stdenv.hostPlatform.isAarch64 then "linux-arm64"
    else if pkgs.stdenv.isLinux && pkgs.stdenv.hostPlatform.isx86_64 then "linux-amd64"
    else throw "Unsupported platform";

  versionInfo = {
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
    genesis = mkMantrachain { version = "v5.0.0-rc3"; };
    "v5.0.0-rc4" = mkMantrachain { version = "v5.0.0-rc4"; };
    "v5.0.0-rc5" = pkgs.callPackage ../../nix/mantrachain { };
  };

in
pkgs.linkFarm "upgrade-test-package-recent" (
  pkgs.lib.mapAttrsToList (name: path: { inherit name path; }) releases
)

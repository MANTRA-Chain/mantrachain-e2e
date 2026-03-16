{
  lib,
  stdenv,
  buildGo125Module,
  fetchFromGitHub,
  fetchurl,
  pkgsStatic,
}:
let
  builder = import ../mantrachain-builder.nix {
    inherit lib stdenv buildGo125Module fetchFromGitHub fetchurl pkgsStatic;
  };
in
builder {
  version = "v8";
  owner = "MANTRA-Chain";
  rev = "77932d8d289d76009a3c918ece2b7519acb36e89";
  hash = "sha256-Bxq5li/TCrKtAtaFnt03AHK6/UXIbawxvaIpHDRVwpw=";
  vendorHash = "sha256-h26r91LLIqy/xz+sFuvpgNMKMCLcNvQJs53Jmri7dM4=";
}

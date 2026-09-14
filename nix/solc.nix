{
  stdenv,
  lib,
  fetchurl,
}:

let
  version = "0.8.28";
  asset = if stdenv.isDarwin then "solc-macos" else "solc-static-linux";
  url = "https://github.com/ethereum/solidity/releases/download/v${version}/${asset}";
  sha256 = if stdenv.isDarwin
    then "sha256-gVFbDlPeqiZtVJVFzKrApalubU6CAcd/ZzsscQl22eo="
    else "sha256-mg+34NssBkHbrhxcxkXcaGggyDr1FiJquxwKL3ZjbyU=";
in
stdenv.mkDerivation {
  pname = "solc";
  inherit version;
  src = fetchurl { inherit url sha256; };
  dontUnpack = true;
  installPhase = ''
    mkdir -p $out/bin
    cp $src $out/bin/solc
    chmod +x $out/bin/solc
  '';
  doInstallCheck = false;
  meta = with lib; {
    description = "Pinned Solidity compiler ${version}";
    homepage = "https://github.com/ethereum/solidity";
    license = licenses.gpl3Plus;
    platforms = platforms.unix;
    mainProgram = "solc";
  };
}
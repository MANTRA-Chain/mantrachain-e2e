{
  src,
  lib,
  stdenv,
  libiconv,
  rustPlatform,
  symlinkJoin,
  openssl,
  pkg-config,
  protobuf,
  clang,
  llvmPackages,
}:

rustPlatform.buildRustPackage rec {
  name = "hermes";
  inherit src;
  cargoBuildFlags = [ "-p" "ibc-relayer-cli" ];
  nativeBuildInputs = [
    pkg-config
    protobuf
    clang
  ];
  buildInputs = [
    openssl
    llvmPackages.libclang.lib
  ] ++ lib.optionals stdenv.isDarwin [ libiconv ];
  cargoLock = {
    lockFile = "${src}/Cargo.lock";
  };
  doCheck = false;
  env = {
    RUSTFLAGS = "--cfg ossl111 --cfg ossl110 --cfg ossl101";
    OPENSSL_NO_VENDOR = "1";
    PROTOC = "${protobuf}/bin/protoc";
    LIBCLANG_PATH = "${llvmPackages.libclang.lib}/lib";
    OPENSSL_DIR = symlinkJoin {
      name = "openssl";
      paths = with openssl; [
        out
        dev
      ];
    };
  };
}

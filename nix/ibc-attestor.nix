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

# Builds the `ibc_attestor` binary from cosmos/ibc-attestor. Mirrors
# eureka-relayer.nix so it drops into the devShell the same way.
rustPlatform.buildRustPackage rec {
  name = "ibc-attestor";
  inherit src;
  cargoBuildFlags = [ "-p" "ibc-attestor" "--bin" "ibc_attestor" ];
  nativeBuildInputs = [
    pkg-config
    protobuf
    clang
  ];
  buildInputs = [
    openssl
    llvmPackages.libclang.lib
  ] ++ lib.optionals stdenv.isDarwin [ libiconv ];
  cargoHash = "sha256-7eCzLBwlmvYXZDrnjHGTADdSLfPZaBbksR4HeUDetw0=";
  doCheck = false;
  env = {
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

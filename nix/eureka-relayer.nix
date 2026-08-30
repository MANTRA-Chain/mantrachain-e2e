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
  name = "ibc-eureka-relayer";
  inherit src;
  cargoBuildFlags = [
    "-p"
    "ibc-eureka-relayer"
  ];
  nativeBuildInputs = [
    pkg-config
    protobuf
    clang
  ];
  buildInputs = [
    openssl
    llvmPackages.libclang.lib
  ]
  ++ lib.optionals stdenv.isDarwin [ libiconv ];

  # Need cargoHash, not cargoLock: workspace has two ibc-proto 0.51.1
  # from different sources; importCargoLock keys by name-version and collides.
  cargoHash = "sha256-GCLMdCOq4C9+wLK0/NXOmVCDr/liTpqe4ePkxW+3IO8=";
  doCheck = false;

  # sp1-core-executor-runner's build.rs runs `cargo metadata` from inside the
  # vendor; fix the unresolved @vendor@ placeholder + drop crate-private locks.
  prePatch = ''
    substituteInPlace "$cargoDepsCopy/.cargo/config.toml" \
      --subst-var-by vendor "$cargoDepsCopy"
    find "$cargoDepsCopy" -mindepth 2 -name Cargo.lock -delete
  '';

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
    # Skip building SP1's inner runner; not needed for packet relay.
    SP1_CORE_RUNNER_OVERRIDE_BINARY = "/bin/sh";
  };
}

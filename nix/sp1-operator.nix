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

# Builds the `operator` binary (package `sp1-ics07-tendermint-operator`) from
# cosmos/solidity-ibc-eureka — the same source tree as eureka-relayer.nix, so it
# drops into the devShell the same way and shares the vendored Cargo deps.
#
# The operator produces the SP1ICS07Tendermint genesis (trusted client/consensus
# state + program vkeys) and proof fixtures. It reads the four program ELFs from
# `--*-path` flags at runtime (see SP1ELFPaths), so the build does NOT need the
# SP1 programs — point those flags at `sp1-ics07-programs` (see that derivation).
rustPlatform.buildRustPackage rec {
  name = "sp1-ics07-tendermint-operator";
  inherit src;
  cargoBuildFlags = [
    "-p"
    "sp1-ics07-tendermint-operator"
    "--bin"
    "operator"
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

  # Same workspace + Cargo.lock as eureka-relayer.nix, so the vendored deps hash
  # matches. If a first build reports a mismatch, copy the expected hash here.
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
    # Skip building SP1's inner runner; genesis + mock proving don't execute the
    # zkVM. Real CPU proving (groth16/plonk) would need this override removed.
    SP1_CORE_RUNNER_OVERRIDE_BINARY = "/bin/sh";
  };
}

{ fetchurl, runCommand }:

# Vendored, prebuilt SP1 ICS07-Tendermint program ELFs (riscv64im-succinct-zkvm).
#
# These are the release assets attached to the `sp1-programs-v2.0.0-rc.2` tag of
# cosmos/solidity-ibc-eureka. We vendor prebuilt binaries instead of building
# the SP1 programs from source, which would require the Succinct toolchain
# (`sp1up` / `cargo-prove`).
#
# Both the operator (genesis vkey derivation) and the relayer (`sp1_programs`
# config + proof generation) must point at the SAME ELF set, or the contract's
# deployed vkeys won't match the prover's — even in mock mode. Pinning one set
# here keeps all three (contract, operator, relayer) consistent.
#
# INVARIANT: the tag's `programs/sp1-programs` tree must equal the one in
# `eureka-relayer-src` (flake.nix) — same program source => same ELF => same
# vkeys the operator/relayer/contract all agree on. Verified for the current
# pins: `git diff <eureka-relayer-src commit>..<this tag's commit> --
# programs/sp1-programs` is empty (only an unrelated rpc.rs helper differs).
# When bumping `eureka-relayer-src`, re-run that diff and bump the tag + sha256s
# here if the program source moved.
let
  tag = "sp1-programs-v2.0.0-rc.2";
  base = "https://github.com/cosmos/solidity-ibc-eureka/releases/download/${tag}";

  # name (as deployed on the release) -> sha256 (from the GitHub release asset digest)
  programs = {
    "sp1-ics07-tendermint-update-client" =
      "6a6a40df2b1339455de7b238fdf3e914f4c2f99e85b8fc4abb65fb1664f42270";
    "sp1-ics07-tendermint-membership" =
      "d3db52d484339ced372a527992470301d96d1a70b10b4131193efb2880ec9541";
    "sp1-ics07-tendermint-uc-and-membership" =
      "e1f409ac50bea3019a1662dfbab6237bfd20aaaff7fb2befee35e6138eeff84e";
    "sp1-ics07-tendermint-misbehaviour" =
      "6ec141ebb604565dfb7669f8482bd3eacc57ae35158ba3931f1c20f78f7bf921";
  };

  fetched = builtins.mapAttrs (
    name: sha256:
    fetchurl {
      url = "${base}/${name}";
      inherit sha256;
    }
  ) programs;

  copyCmds = builtins.concatStringsSep "\n" (
    builtins.attrValues (builtins.mapAttrs (name: drv: "cp ${drv} $out/${name}") fetched)
  );
in
# Assemble the four ELFs into a single store dir with their canonical names, so
# callers can reference e.g. `${sp1-ics07-programs}/sp1-ics07-tendermint-membership`.
runCommand "sp1-ics07-programs-${tag}" { passthru = { inherit tag; }; } ''
  mkdir -p $out
  ${copyCmds}
''

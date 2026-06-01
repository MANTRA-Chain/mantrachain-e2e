"""SP1 ICS07-Tendermint deploy helpers (cosmos→EVM leg), the counterpart to
:mod:`eureka_deploy`: run the operator for genesis, deploy the groth16 verifier +
``SP1ICS07Tendermint``, and register it on ICS26Router.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from eth_account import Account
from eth_account.signers.base import BaseAccount
from eth_utils import keccak
from web3 import AsyncWeb3
from web3.contract import AsyncContract

from .eureka_deploy import _add_client, _deploy

# ELF filenames in the `sp1-ics07-programs` derivation (also the operator's
# --*-path flags), resolved from SP1_ICS07_PROGRAMS_DIR.
ELF_NAMES = {
    "update_client": "sp1-ics07-tendermint-update-client",
    "membership": "sp1-ics07-tendermint-membership",
    "uc_and_membership": "sp1-ics07-tendermint-uc-and-membership",
    "misbehaviour": "sp1-ics07-tendermint-misbehaviour",
}

# Must match across genesis, the deployed verifier, and the relayer's sp1_prover
# config. groth16 = cheaper/faster on-chain verify; pairs with SP1VerifierGroth16.
DEFAULT_PROOF_TYPE = "groth16"  # or "plonk"


def _unhex(s: str) -> bytes:
    """Decode a ``0x``-prefixed (or bare) hex string to bytes."""
    return bytes.fromhex(s.removeprefix("0x"))


# ---------------------------------------------------------------------------
# Genesis (output of `operator`)
# ---------------------------------------------------------------------------


@dataclass
class SP1ICS07Genesis:
    """Mirror of upstream ``SP1ICS07TendermintGenesis`` (camelCase JSON)."""

    trusted_client_state: bytes  # ABI-encoded ClientState
    trusted_consensus_state: bytes  # ABI-encoded ConsensusState
    update_client_vkey: bytes  # bytes32
    membership_vkey: bytes
    uc_and_membership_vkey: bytes
    misbehaviour_vkey: bytes

    @classmethod
    def from_fixture(cls, doc: dict) -> "SP1ICS07Genesis":
        """Extract the genesis fields embedded in an operator fixture JSON."""
        return cls(
            trusted_client_state=_unhex(doc["trustedClientState"]),
            trusted_consensus_state=_unhex(doc["trustedConsensusState"]),
            update_client_vkey=_unhex(doc["updateClientVkey"]),
            membership_vkey=_unhex(doc["membershipVkey"]),
            uc_and_membership_vkey=_unhex(doc["ucAndMembershipVkey"]),
            misbehaviour_vkey=_unhex(doc["misbehaviourVkey"]),
        )

    @property
    def consensus_state_hash(self) -> bytes:
        """bytes32 commitment the constructor stores — keccak256, not the bytes."""
        return keccak(self.trusted_consensus_state)


def _elf_paths() -> dict[str, str]:
    base = os.environ.get("SP1_ICS07_PROGRAMS_DIR")
    if base is None:
        raise RuntimeError(
            "SP1_ICS07_PROGRAMS_DIR not set; point it at the sp1-ics07-programs "
            "nix store dir (the devShell should export it)"
        )
    base_path = Path(base)
    return {key: str(base_path / name) for key, name in ELF_NAMES.items()}


def _operator_update_client_fixture(
    *,
    tendermint_rpc_url: str,
    trusted_block: int,
    target_block: int,
    proof_type: str,
    operator_bin: str,
    prover: str,
) -> dict:
    """Run ``operator fixtures update-client`` (no standalone genesis subcommand)
    and return the parsed JSON — genesis fields + an update proof (``updateMsg`` /
    ``targetHeight``). ``prover='mock'`` for genesis-only; ``'cpu'``/``'network'``
    for a real proof."""
    elfs = _elf_paths()
    args = [
        operator_bin,
        "fixtures",
        "update-client",
        "--trusted-block",
        str(trusted_block),
        "--target-block",
        str(target_block),
        "-p",
        proof_type,
        "--update-client-path",
        elfs["update_client"],
        "--membership-path",
        elfs["membership"],
        "--uc-and-membership-path",
        elfs["uc_and_membership"],
        "--misbehaviour-path",
        elfs["misbehaviour"],
        "-o",
        "-",  # stdout
    ]
    env = {**os.environ, "TENDERMINT_RPC_URL": tendermint_rpc_url, "SP1_PROVER": prover}
    proc = subprocess.run(args, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        # Full stderr (the verifier verdict) — CalledProcessError's repr truncates it.
        raise RuntimeError(
            f"operator update-client failed (exit {proc.returncode})\n"
            f"cmd: {' '.join(args)}\n"
            f"--- stderr ---\n{proc.stderr}\n--- stdout ---\n{proc.stdout}"
        )
    return json.loads(proc.stdout)


def run_operator_genesis(
    *,
    tendermint_rpc_url: str,
    trusted_block: int,
    target_block: int | None = None,
    proof_type: str = DEFAULT_PROOF_TYPE,
    operator_bin: str = "operator",
    prover: str = "mock",
) -> SP1ICS07Genesis:
    """Genesis (trusted state + vkeys) for deploying SP1ICS07Tendermint. vkeys are
    ELF-derived (prover-independent), so mock is the default (fast)."""
    doc = _operator_update_client_fixture(
        tendermint_rpc_url=tendermint_rpc_url,
        trusted_block=trusted_block,
        target_block=target_block or trusted_block + 1,
        proof_type=proof_type,
        operator_bin=operator_bin,
        prover=prover,
    )
    return SP1ICS07Genesis.from_fixture(doc)


@dataclass
class SP1UpdateFixture:
    """Genesis + a real update proof for the same trusted→target window."""

    genesis: SP1ICS07Genesis
    update_msg: bytes  # abi-encoded MsgUpdateClient (carries the SP1Proof)
    target_height: int


def run_operator_update_client(
    *,
    tendermint_rpc_url: str,
    trusted_block: int,
    target_block: int,
    proof_type: str = DEFAULT_PROOF_TYPE,
    operator_bin: str = "operator",
    prover: str = "cpu",
) -> SP1UpdateFixture:
    """Genesis + a real update proof in one operator run (default cpu prover);
    submit ``update_msg`` to ``SP1ICS07Tendermint.updateClient``."""
    doc = _operator_update_client_fixture(
        tendermint_rpc_url=tendermint_rpc_url,
        trusted_block=trusted_block,
        target_block=target_block,
        proof_type=proof_type,
        operator_bin=operator_bin,
        prover=prover,
    )
    return SP1UpdateFixture(
        genesis=SP1ICS07Genesis.from_fixture(doc),
        update_msg=_unhex(doc["updateMsg"]),
        target_height=int(doc["targetHeight"]),
    )


# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------


@dataclass
class DeployedSP1Client:
    verifier: AsyncContract
    light_client: AsyncContract
    genesis: SP1ICS07Genesis
    client_id: str
    counterparty_client_id: str


async def deploy_sp1_verifier(
    w3: AsyncWeb3, deployer: BaseAccount, *, mock: bool = False
) -> AsyncContract:
    """Deploy the SP1 verifier — real groth16 by default (must match the ELFs:
    v6.1.0 ⇄ sp1-zkvm 6.1). ``mock`` accepts any proof (deploy-only smoke)."""
    return await _deploy(
        w3, deployer, "SP1MockVerifier" if mock else "SP1VerifierGroth16"
    )


async def deploy_sp1_ics07_client(
    w3: AsyncWeb3,
    deployer: BaseAccount,
    genesis: SP1ICS07Genesis,
    verifier: AsyncContract,
    *,
    role_manager: str = "0x" + "00" * 20,
) -> AsyncContract:
    """Deploy ``SP1ICS07Tendermint`` from a genesis + verifier. Constructor:
    (4 program vkeys, sp1Verifier, _clientState bytes, _consensusState bytes32
    commitment, roleManager)."""
    return await _deploy(
        w3,
        deployer,
        "SP1ICS07Tendermint",
        genesis.update_client_vkey,
        genesis.membership_vkey,
        genesis.uc_and_membership_vkey,
        genesis.misbehaviour_vkey,
        verifier.address,
        genesis.trusted_client_state,
        genesis.consensus_state_hash,
        role_manager,
    )


async def deploy_sp1_light_client(
    w3: AsyncWeb3,
    deployer_key: bytes | str,
    *,
    tendermint_rpc_url: str,
    trusted_block: int,
    ics26_router: AsyncContract,
    counterparty_client_id: str,
    target_block: int | None = None,
    verifier_mock: bool = False,
    proof_type: str = DEFAULT_PROOF_TYPE,
    merkle_prefix: list[bytes] | None = None,
) -> DeployedSP1Client:
    """genesis (mock-extracted, fast) → verifier (real groth16 unless
    ``verifier_mock``) → SP1ICS07Tendermint → ``addClient`` on ICS26Router.
    Needs the Eureka stack deployed with the SAME ``deployer_key`` (for
    ID_CUSTOMIZER_ROLE). ``merkle_prefix`` defaults to the cosmos store prefix."""
    deployer = Account.from_key(deployer_key)
    genesis = run_operator_genesis(
        tendermint_rpc_url=tendermint_rpc_url,
        trusted_block=trusted_block,
        target_block=target_block,
        proof_type=proof_type,
        prover="mock",
    )
    verifier = await deploy_sp1_verifier(w3, deployer, mock=verifier_mock)
    light_client = await deploy_sp1_ics07_client(w3, deployer, genesis, verifier)

    # Register the SP1 client on ICS26Router (same public addClient overload the
    # attestation/dummy path uses); the router assigns the local clientId.
    client_id = await _add_client(
        w3,
        deployer,
        ics26_router,
        counterparty_client_id=counterparty_client_id,
        light_client_addr=light_client.address,
        merkle_prefix=merkle_prefix if merkle_prefix is not None else [b"ibc", b""],
    )

    return DeployedSP1Client(
        verifier=verifier,
        light_client=light_client,
        genesis=genesis,
        client_id=client_id,
        counterparty_client_id=counterparty_client_id,
    )

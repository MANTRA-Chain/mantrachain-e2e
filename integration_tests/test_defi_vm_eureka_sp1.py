from __future__ import annotations

import asyncio
import os
import platform
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from eth_account import Account
from eth_contract import ERC20
from eth_contract.utils import send_transaction
from ibc_eureka.contracts.deploy import deploy_eureka_stack
from ibc_eureka.contracts.deploy_sp1 import (
    deploy_sp1_ics07_client,
    deploy_sp1_light_client,
    deploy_sp1_verifier,
    run_operator_update_client,
)
from ibc_eureka.harness.process import require_binary
from ibc_eureka.harness.relayer import (
    _server_observability,
    _sp1,
    build_eth_to_cosmos_sp1_config,
    start_relayer,
)
from hexbytes import HexBytes
from pystarport.utils import wait_for_new_blocks

from .eureka_artifacts import find_eureka_repo, get_contract
from .network import setup_custom_mantra
from .utils import KEYS, free_port

if TYPE_CHECKING:
    from ibc_eureka.relayer.binary import BinaryRelayer, _Endpoint

try:
    find_eureka_repo()
    pytestmark = pytest.mark.asyncio
except FileNotFoundError as _exc:
    pytestmark = [pytest.mark.asyncio, pytest.mark.skip(reason=str(_exc))]

_OPERATOR_BIN = "operator"
# Community key holds ID_CUSTOMIZER_ROLE after deploy_eureka_stack. KEYS["community"]
# is the raw key for deploy helpers; _DEPLOYER the Account for signing raw txs.
_DEPLOYER = Account.from_key(KEYS["community"])


@pytest.fixture(scope="module")
def sp1_mantra(request, tmp_path_factory):
    """Mantra chain with realistic unbonding_time (configs/sp1.jsonnet); the
    default 10s makes the trusting period (~6.7s) expire every trusted header."""
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp("sp1_mantra")
    cfg = Path(__file__).parent / "configs" / "sp1.jsonnet"
    yield from setup_custom_mantra(path, 26750, cfg, chain=chain)


@pytest.fixture(scope="module")
def sp1_programs_dir() -> str:
    """Skip unless the SP1 prerequisites are present (operator binary + ELFs)."""
    try:
        require_binary(_OPERATOR_BIN)
    except FileNotFoundError as exc:
        pytest.skip(str(exc))
    programs_dir = os.environ.get("SP1_ICS07_PROGRAMS_DIR")
    if not programs_dir:
        pytest.skip(
            "SP1_ICS07_PROGRAMS_DIR not set — the devShell must export the "
            "sp1-ics07-programs store dir"
        )
    return programs_dir


@pytest.fixture(scope="module")
def sp1_real_verifier() -> None:
    """Skip unless the v6.1.0 groth16 verifier compiles (needs `bun install` in
    solidity-ibc-eureka; node_modules may ship older sp1-contracts)."""
    try:
        get_contract("SP1VerifierGroth16")
    except FileNotFoundError as exc:
        pytest.skip(
            f"SP1VerifierGroth16 v6.1.0 unavailable — run `bun install` in "
            f"solidity-ibc-eureka: {exc}"
        )


def _tendermint_http_rpc(mantra) -> str:
    """The http:// CometBFT RPC (node_rpc gives tcp://) — used both by the operator
    and as the relayer's tm_rpc_url."""
    return mantra.node_rpc(0).replace("tcp://", "http://")


def _recent_window(mantra, *, settle: int = 8) -> tuple[int, int]:
    """Settle a few blocks, then a non-adjacent ``(trusted, target)`` window. The
    realistic unbonding (configs/sp1.jsonnet) keeps the trusting period > latency."""
    cli = mantra.cosmos_cli()
    wait_for_new_blocks(cli, settle)
    height = cli.block_height()
    return height - 4, height - 1


def _real_proof_prover_or_skip() -> str:
    """Resolve the SP1 prover for a real-proof test, or skip. Explicit SP1_PROVER
    wins; else network if NETWORK_* present, else local cpu. The gnark wrap is
    amd64/AVX-only, so on arm64 a local prover skips unless SP1_ALLOW_ARM64_WRAP=1
    (slow QEMU; Rosetta SIGILLs)."""
    if not os.environ.get("SP1_REAL_PROOF"):
        pytest.skip("set SP1_REAL_PROOF=1 to run the real-proof test")
    prover = os.environ.get("SP1_PROVER") or (
        "network" if os.environ.get("NETWORK_PRIVATE_KEY") else "cpu"
    )
    if (
        prover in ("cpu", "cuda")
        and platform.machine() == "arm64"
        and not os.environ.get("SP1_ALLOW_ARM64_WRAP")
    ):
        pytest.skip(
            "local groth16 wrap (gnark) is amd64/AVX-only; Rosetta can't run it. "
            "Use amd64 CI / SP1_PROVER=network, or disable Rosetta (→ QEMU) and "
            "set SP1_ALLOW_ARM64_WRAP=1 to attempt the slow emulated path"
        )
    return prover


async def test_sp1_create_client(sp1_mantra, sp1_programs_dir, sp1_real_verifier):
    """Deploy + register SP1ICS07Tendermint (real verifier); assert a real clientId
    (≠ dummy) and getClientState() answers. No proof verified at create."""
    w3 = sp1_mantra.async_w3
    stack = await deploy_eureka_stack(w3, KEYS["community"])
    trusted_block, target_block = _recent_window(sp1_mantra)

    deployed = await deploy_sp1_light_client(
        w3,
        KEYS["community"],
        tendermint_rpc_url=_tendermint_http_rpc(sp1_mantra),
        trusted_block=trusted_block,
        target_block=target_block,
        ics26_router=stack.ics26_router,
        counterparty_client_id="07-tendermint-0",
        verifier_mock=False,  # real groth16 verifier
    )

    assert deployed.client_id, "ICS26Router assigned no clientId"
    assert deployed.client_id != stack.client_id, "SP1 client collided with dummy"

    client_state = await deployed.light_client.functions.getClientState().call()
    assert client_state, "empty ClientState from deployed SP1 client"


async def test_sp1_update_client(sp1_mantra, sp1_programs_dir, sp1_real_verifier):
    """Submit a real update proof; the on-chain groth16 verifier must accept it.
    Gated behind SP1_REAL_PROOF=1. Uses the Succinct network prover when
    NETWORK_PRIVATE_KEY is set (fast); else local cpu (slow/heavy)."""
    prover = _real_proof_prover_or_skip()

    w3 = sp1_mantra.async_w3
    trusted_block, target_block = _recent_window(sp1_mantra)

    # One operator run: genesis @ trusted + a real groth16 proof trusted→target.
    fixture = run_operator_update_client(
        tendermint_rpc_url=_tendermint_http_rpc(sp1_mantra),
        trusted_block=trusted_block,
        target_block=target_block,
        proof_type="groth16",
        prover=prover,
    )

    verifier = await deploy_sp1_verifier(w3, _DEPLOYER, mock=False)
    client = await deploy_sp1_ics07_client(w3, _DEPLOYER, fixture.genesis, verifier)

    # Submit the real proof; SP1ICS07Tendermint.updateClient calls the on-chain
    # verifier, which reverts if the proof is invalid or its version mismatches.
    tx = await client.functions.updateClient(fixture.update_msg).build_transaction(
        {"from": _DEPLOYER.address}
    )
    receipt = await send_transaction(w3, _DEPLOYER, **tx)
    assert receipt["status"] == 1, "on-chain groth16 verifier rejected the real proof"


async def test_sp1_relayer_config_loads(sp1_mantra, sp1_programs_dir):
    """Schema smoke: the relayer boots with a cosmos_to_eth module in {"sp1": …}
    mode (mock prover — never reaches the gnark wrap), confirming it parses the
    _sp1 config. Runs anywhere."""
    try:
        require_binary("relayer")
    except FileNotFoundError as exc:
        pytest.skip(str(exc))

    w3 = sp1_mantra.async_w3
    stack = await deploy_eureka_stack(w3, KEYS["community"])
    eth_chain_id = hex(await w3.eth.chain_id)

    config = {
        **_server_observability(free_port(), free_port(), "info"),
        "modules": [
            {
                "name": "cosmos_to_eth",
                "src_chain": sp1_mantra.cosmos_cli().chain_id,
                "dst_chain": eth_chain_id,
                "config": {
                    "tm_rpc_url": _tendermint_http_rpc(sp1_mantra),
                    "ics26_address": stack.ics26_router.address,
                    "eth_rpc_url": sp1_mantra.w3_http_endpoint(),
                    "mode": _sp1(sp1_programs_dir, prover="mock"),
                },
            }
        ],
    }

    proc = start_relayer(config, work_dir=Path(sp1_mantra.base_dir) / "sp1_relayer")
    try:
        # Bound gRPC port ⇒ the relayer accepted the {"sp1": …} config.
        assert proc.grpc_address, "relayer did not bind — SP1 config rejected?"
    finally:
        proc.stop()


# ---------------------------------------------------------------------------
# Full packet flow: cosmos→EVM recv (membership) + EVM→cosmos timeout (absence).
# ---------------------------------------------------------------------------


@dataclass
class SP1CosmosToEthStack:
    """What the transfer + timeout tests read; the relayer/attestor processes are
    owned + torn down by the fixture, not held here."""

    mantra: Any
    eth_w3: Any
    denom: str  # cosmos fee/bond denom (atest)
    cosmos_chain_id: str
    cosmos_client_id: str  # attestations-0 (cosmos side, tracks EVM)
    cosmos_ep: _Endpoint  # chain_id=cosmos, client_id=attestations-0
    eth_chain_id: str  # EVM chain id, hex
    eth_client_id: str  # SP1 client on EVM, tracks CometBFT
    eth_transfer_addr: Any  # ICS20Transfer proxy (sendTransfer / escrow)
    eth_test_erc20_addr: Any  # TestERC20 the EVM source escrows
    relayer: BinaryRelayer  # .src is the SP1 EVM endpoint (relay dest)


# Module-scoped so the transfer + timeout tests share ONE setup (one attestations
# client, one SP1 client, one relayer) — re-running it per test would create
# attestations-1 on the reused chain and break the deterministic counterparty.
# Mirrors the attestor eth_to_cosmos_eureka_stack scope.
@pytest.fixture(scope="module")
async def sp1_cosmos_to_eth_stack(
    sp1_mantra, sp1_programs_dir, sp1_real_verifier, tmp_path_factory
):
    """Mirrors the attestor ``eth_to_cosmos_eureka_stack``, swapping the EVM-side
    client (→ SP1ICS07Tendermint, real groth16) + the relayer's cosmos_to_eth leg
    (→ SP1). The reverse eth→cosmos leg stays attested (eth attestor + cosmos
    attestations client). Gated like test_sp1_update_client."""
    from ibc_eureka.harness.attestor import Attestor
    from ibc_eureka.relayer.binary import BinaryRelayer, _Endpoint

    from .eureka_cosmos import _clean_bech32, add_counterparty, cosmos_signer

    prover = _real_proof_prover_or_skip()
    try:
        require_binary("relayer")
    except FileNotFoundError as exc:
        pytest.skip(str(exc))

    eth_w3 = sp1_mantra.async_w3
    cli = sp1_mantra.cosmos_cli()
    relayer_signer = "signer1"  # funded cosmos submitter
    denom = cli.get_params("staking")["bond_denom"]
    cosmos_chain_id = cli.chain_id
    cosmos_rpc = _tendermint_http_rpc(sp1_mantra)
    eth_chain_id = hex(await eth_w3.eth.chain_id)
    cosmos_client_id = "attestations-0"  # deterministic on a fresh evmd

    # Base EVM stack (dummy client-0); deploy_sp1_light_client then adds the real
    # SP1 client tracking CometBFT and returns its assigned local id.
    base = await deploy_eureka_stack(eth_w3, KEYS["community"])

    trusted_block, target_block = _recent_window(sp1_mantra)
    sp1 = await deploy_sp1_light_client(
        eth_w3,
        KEYS["community"],
        tendermint_rpc_url=_tendermint_http_rpc(sp1_mantra),
        trusted_block=trusted_block,
        target_block=target_block,
        ics26_router=base.ics26_router,
        counterparty_client_id=cosmos_client_id,
        verifier_mock=False,
        # Real ICS23 against CometBFT's "ibc" store ⇒ the cosmos store prefix
        # (not the attestor's [b""]).
        merkle_prefix=[b"ibc", b""],
    )
    eth_client_id = sp1.client_id

    # Eth attestor: only the reverse (eth→cosmos) leg is attested; the cosmos
    # attestations client tracking EVM trusts this attestor.
    eth_attestor = Attestor(tmp_path_factory.mktemp("sp1_att_eth"))
    eth_attestor.start(
        rpc_url=sp1_mantra.w3_http_endpoint(),
        router_address=base.ics26_router.address,
        chain_type="evm",
    )

    config = build_eth_to_cosmos_sp1_config(
        grpc_port=free_port(),
        grpc_web_port=free_port(),
        eth_chain_id=eth_chain_id,
        eth_rpc_url=sp1_mantra.w3_http_endpoint(),
        eth_ics26_address=base.ics26_router.address,
        eth_attestor_endpoint=eth_attestor.grpc_endpoint,
        cosmos_chain_id=cosmos_chain_id,
        cosmos_rpc_url=cosmos_rpc,
        cosmos_signer_address=_clean_bech32(cli.address(relayer_signer)),
        sp1_programs_dir=sp1_programs_dir,
        sp1_prover=prover,
    )
    work_dir = tmp_path_factory.mktemp("sp1_cosmos_to_eth_relayer")
    relayer_process = start_relayer(config, work_dir=work_dir)

    # relay() only reads .chain_id + .client_id. src = the SP1 EVM client (recv
    # dest); cosmos_ep names the cosmos source client.
    eth_ep = _Endpoint(
        w3=eth_w3,
        router_addr=base.ics26_router.address,
        client_id=eth_client_id,
        chain_id=eth_chain_id,
        deployer=_DEPLOYER,
    )
    cosmos_ep = _Endpoint(
        w3=eth_w3,
        router_addr=base.ics26_router.address,
        client_id=cosmos_client_id,
        chain_id=cosmos_chain_id,
        deployer=_DEPLOYER,
    )
    relayer = BinaryRelayer(
        src=eth_ep, dst=eth_ep, grpc_address=relayer_process.grpc_address
    )

    # Cosmos attestations client tracking EVM + wire the v2 counterparty both ways
    # (cosmos attestations-0 ↔ EVM SP1 client).
    eth_block = await eth_w3.eth.get_block("latest")
    created = relayer.create_attestations_client(
        eth_chain_id=eth_chain_id,
        cosmos_chain_id=cosmos_chain_id,
        attestor_addresses=[eth_attestor.address],
        height=eth_block["number"],
        timestamp=eth_block["timestamp"],
        cosmos_signer=cosmos_signer(sp1_mantra, relayer_signer, denom=denom),
    )
    assert created == cosmos_client_id, f"expected {cosmos_client_id}, got {created}"
    # EVM commitment prefix is a single empty element (matches the attestor stack).
    add_counterparty(
        sp1_mantra, relayer_signer, cosmos_client_id, eth_client_id, [b""], denom=denom
    )

    try:
        yield SP1CosmosToEthStack(
            mantra=sp1_mantra,
            eth_w3=eth_w3,
            denom=denom,
            cosmos_chain_id=cosmos_chain_id,
            cosmos_client_id=cosmos_client_id,
            cosmos_ep=cosmos_ep,
            eth_chain_id=eth_chain_id,
            eth_client_id=eth_client_id,
            eth_transfer_addr=base.ics20_transfer.address,
            eth_test_erc20_addr=base.test_erc20.address,
            relayer=relayer,
        )
    finally:
        relayer.close()
        relayer_process.stop()
        eth_attestor.stop()


async def test_sp1_transfer_cosmos_to_evm(sp1_cosmos_to_eth_stack):
    """Full cosmos→EVM packet flow: a native ICS20-v2 send relayed to EVM. The
    relayer builds an update_client_and_membership proof SP1ICS07Tendermint verifies
    on-chain before ICS26Router routes the recv — recv status==1 is the end-to-end
    SP1 assertion (a bad proof reverts). Slow; gated like test_sp1_update_client."""
    from .eureka_cosmos import send_v2_transfer

    stack = sp1_cosmos_to_eth_stack
    amount = 10**6
    eth_receiver = Account.from_key(KEYS["signer1"]).address  # clean EVM recipient

    cosmos_send = send_v2_transfer(
        stack.mantra,
        "signer2",
        source_client=stack.cosmos_client_id,
        receiver=eth_receiver,
        token_denom=stack.denom,
        amount=amount,
        timeout_timestamp=int(time.time()) + 600,
        fee_denom=stack.denom,
    )
    assert cosmos_send["code"] == 0, cosmos_send.get("raw_log")

    # Advance past the commit height first: the relayer proves at target_height-1
    # (proof-api rpc.rs::prove_path), so relaying at the commit block proves the
    # commitment absent → MembershipProofValueMismatch(_, empty).
    wait_for_new_blocks(stack.mantra.cosmos_cli(), 2)

    # The slow step: relayer builds the SP1 proof, EVM verifies + routes the recv.
    recv = await stack.relayer.relay(
        stack.cosmos_ep, stack.relayer.src, bytes.fromhex(cosmos_send["txhash"])
    )
    assert recv["status"] == 1, "SP1 recvPacket failed — groth16/membership rejected"


async def test_sp1_timeout_evm_to_cosmos(sp1_cosmos_to_eth_stack):
    """SP1 non-membership: an EVM→cosmos transfer with a short timeout whose recv is
    never relayed; relaying the timeout refunds the EVM sender by proving the cosmos
    receipt ABSENT (over receipt_commitment_path), verified by the EVM-side SP1
    client. Slow; gated like test_sp1_update_client."""
    from .eureka_cosmos import _clean_bech32

    try:
        from pydefi.bridge import encode_send_transfer_calldata
    except Exception as exc:  # pydefi not importable in this env
        pytest.skip(f"pydefi.bridge unavailable: {exc}")

    stack = sp1_cosmos_to_eth_stack
    eth_w3 = stack.eth_w3
    amount = 10**6
    receiver = _clean_bech32(stack.mantra.cosmos_cli().address("signer2"))

    sender_before = await ERC20.fns.balanceOf(_DEPLOYER.address).call(
        eth_w3, to=stack.eth_test_erc20_addr
    )

    # approve + sendTransfer on EVM with a short timeout; source = the SP1 client.
    await ERC20.fns.approve(stack.eth_transfer_addr, amount).transact(
        eth_w3, _DEPLOYER, to=stack.eth_test_erc20_addr
    )
    calldata = encode_send_transfer_calldata(
        denom=HexBytes(stack.eth_test_erc20_addr),
        amount=amount,
        receiver=receiver,
        source_client=stack.eth_client_id,
        timeout_timestamp=int(time.time()) + 8,
    )
    send_receipt = await send_transaction(
        eth_w3, _DEPLOYER, to=stack.eth_transfer_addr, data=calldata, gas=900_000
    )
    assert send_receipt["status"] == 1

    # Don't relay the recv: wait past the timeout + advance blocks so the proof
    # anchors beyond it (receipt provably absent).
    await asyncio.sleep(12)
    wait_for_new_blocks(stack.mantra.cosmos_cli(), 3)

    # The slow step: relayer builds the SP1 non-receipt proof, EVM refunds.
    timeout_receipt = await stack.relayer.relay_timeout(
        src_chain=stack.cosmos_chain_id,
        dst_chain=stack.eth_chain_id,
        src_client_id=stack.cosmos_client_id,
        dst_client_id=stack.eth_client_id,
        timeout_tx_hash=bytes(send_receipt["transactionHash"]),
        to_side=stack.relayer.src,
    )
    msg = "SP1 timeoutPacket failed — groth16/absence proof rejected"
    assert timeout_receipt["status"] == 1, msg

    sender_after = await ERC20.fns.balanceOf(_DEPLOYER.address).call(
        eth_w3, to=stack.eth_test_erc20_addr
    )
    assert sender_after == sender_before, "timeout should refund the EVM sender"

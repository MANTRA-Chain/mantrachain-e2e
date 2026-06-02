from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest
from eth_abi.abi import decode as abi_decode
from eth_abi.abi import encode as abi_encode
from eth_account import Account
from eth_account.signers.base import BaseAccount
from eth_contract import ERC20, Contract
from eth_contract.utils import send_transaction
from eth_typing import ChecksumAddress
from eth_utils.address import to_checksum_address
from hexbytes import HexBytes
from pystarport.utils import wait_for_new_blocks

# Skip if pydefi's packaged data is missing (broken wheel on CI).
try:
    from pydefi.bridge import Eureka, encode_send_transfer_calldata
    from pydefi.types import BasePool, ChainId, RouteDAG, SwapProtocol, Token
    from pydefi.vm import (
        IIBC_SENDER_CALLBACKS_INTERFACE_ID,
        Program,
        approve_then_send_transfer,
        build_execution_program_for_dag,
        encode_send_and_compose_calldata,
    )
except FileNotFoundError as _exc:
    pytest.skip(f"pydefi packaged data missing: {_exc}", allow_module_level=True)
from ibc_eureka.contracts.deploy import ICS20_DEFAULT_PORT, deploy_eureka_stack
from web3 import AsyncWeb3

from .eureka_artifacts import (
    MOCK_V3_POOL_SOL,
    compile_inline,
    compile_pydefi_contract,
    find_eureka_repo,
    get_contract,
)
from .eureka_cosmos import (
    cosmos_signer,
    ibc_voucher_balances,
    send_v2_transfer,
)
from .utils import ACCOUNTS, ADDRS, KEYS, build_and_deploy_contract_async, eth_to_bech32

if TYPE_CHECKING:
    from ibc_eureka.harness.relayer import RelayerProcess
    from ibc_eureka.relayer.binary import BinaryRelayer, _Endpoint

# Every test in this file needs the upstream solidity-ibc-eureka source tree
# (for solc compile + ABIs). Skip the whole module on a clean clone where it
# isn't present, instead of guarding each test individually.
try:
    find_eureka_repo()
    pytestmark = pytest.mark.asyncio
except FileNotFoundError as _exc:
    pytestmark = [pytest.mark.asyncio, pytest.mark.skip(reason=str(_exc))]

# Initial TestERC20 supply minted to the deployer + amount funded into DeFiVM
# (for both USDC and WETH sides). 10**24 = 1M tokens at 18 decimals.
_FUND_AMOUNT = 10**24

# Uniswap V3 pool swap interface — used to encode calldata for the EOA-side test.
_V3_POOL = Contract.from_abi(
    [
        "function swap(address recipient, bool zeroForOne, int256 amountSpecified, "
        "uint160 sqrtPriceLimitX96, bytes data) returns (int256, int256)"
    ]
)


@dataclass
class EurekaStack:
    """Resources produced by the :func:`eureka_stack` fixture.

    Each contract is stored as a ``(Contract, address)`` pair — ``Contract`` is
    eth_contract's address-less ABI wrapper, so callers pass ``to=<addr>`` per
    call. ERC20 calls reuse the shared :data:`eth_contract.ERC20` constant.
    Single-chain shape: ``dst_w3`` aliases ``src_w3``; ``relayer`` drives
    ack/timeout on the src router directly (see :class:`_LocalRelayer`).
    """

    src_w3: AsyncWeb3
    dst_w3: AsyncWeb3
    src_router: Contract
    src_router_addr: ChecksumAddress
    src_transfer: Contract
    src_transfer_addr: ChecksumAddress
    defivm: Contract
    defivm_addr: ChecksumAddress
    test_erc20_addr: ChecksumAddress
    src_client_id: str
    dst_client_id: str
    relayer: Any  # _LocalRelayer — `.deliver_ack()` / `.deliver_timeout()`
    composer: Contract | None = None
    composer_addr: ChecksumAddress | None = None
    light_client: Contract | None = None
    light_client_addr: ChecksumAddress | None = None
    v3_pool: BasePool | None = None
    weth_token: Token | None = None
    usdc_token: Token | None = None
    usdc_token_dst: Token | None = None


async def observe_send_packets(
    w3: AsyncWeb3,
    router: Contract,
    router_addr: ChecksumAddress,
    *,
    from_block: int,
    to_block: int,
) -> list[dict]:
    """Return the decoded ``SendPacket`` event args from ``router`` in the given
    block range (usually one tx's ``blockNumber``). ``["packet"]`` is the tuple
    consumed by :func:`_packet_to_call_tuple`."""
    logs = await router.events.SendPacket.get_logs(
        w3, address=router_addr, from_block=from_block, to_block=to_block
    )
    return [dict(log["args"]) for log in logs]


class _LocalRelayer:
    """Single-chain stand-in: drives ack/timeout on the src router directly via
    a forged ack value + dummy proof (see :func:`eureka_stack`)."""

    def __init__(
        self,
        w3: AsyncWeb3,
        router: Contract,
        router_addr: ChecksumAddress,
        deployer: BaseAccount,
    ) -> None:
        self._w3 = w3
        self._router = router
        self._router_addr = router_addr
        self._deployer = deployer

    async def deliver_ack(self, packet, ack: bytes = b'{"result":"AQ=="}'):
        receipt = await self._router.fns.ackPacket(
            (_packet_to_call_tuple(packet), ack, _DUMMY_PROOF, _DUMMY_HEIGHT)
        ).transact(self._w3, self._deployer, to=self._router_addr)
        assert receipt["status"] == 1
        return receipt

    async def deliver_timeout(self, packet):
        receipt = await self._router.fns.timeoutPacket(
            (_packet_to_call_tuple(packet), _DUMMY_PROOF, _DUMMY_HEIGHT)
        ).transact(self._w3, self._deployer, to=self._router_addr)
        assert receipt["status"] == 1
        return receipt


async def _deploy(
    w3: AsyncWeb3, deployer: BaseAccount, artifact: dict, *args
) -> ChecksumAddress:
    """Deploy from a ``{abi, bin}`` artifact; return the new contract address."""
    contract = Contract(artifact["abi"])
    bytecode = bytes.fromhex(artifact["bin"])
    ctor = contract.constructor(*args).data if contract.constructor else b""
    receipt = await send_transaction(w3, deployer, data=bytecode + ctor)
    addr = receipt["contractAddress"]
    assert addr is not None, "deploy returned no contractAddress"
    return addr


# DummyLightClient.verify(Non)Membership ignores both proof bytes and height
# (returns the configured membershipResult), so any non-empty values work.
_DUMMY_PROOF = b"\x01"
_DUMMY_HEIGHT = (0, 0)


def _packet_to_call_tuple(packet) -> tuple:
    return (
        int(packet["sequence"]),
        packet["sourceClient"],
        packet["destClient"],
        int(packet["timeoutTimestamp"]),
        [
            (
                p["sourcePort"],
                p["destPort"],
                p["version"],
                p["encoding"],
                bytes(p["value"]),
            )
            for p in packet["payloads"]
        ],
    )


async def _compose_and_get_packet(
    stack: EurekaStack,
    deployer: BaseAccount,
    *,
    amount: int,
    program_bytes: bytes,
    receiver: str,
    timeout_seconds: int = 600,
) -> tuple[dict, int]:
    """Approve composer, call ``sendTransferAndCompose`` via
    :func:`encode_send_and_compose_calldata`, drain the relayer, and return
    ``(packet_dict, sequence)`` for the just-sent packet."""
    assert stack.composer_addr is not None
    src_w3 = stack.src_w3
    await ERC20.fns.approve(stack.composer_addr, amount).transact(
        src_w3, deployer, to=stack.test_erc20_addr
    )
    calldata = encode_send_and_compose_calldata(
        denom=HexBytes(stack.test_erc20_addr),
        amount=amount,
        receiver=receiver,
        source_client=stack.src_client_id,
        timeout_timestamp=int(time.time()) + timeout_seconds,
        program=program_bytes,
    )
    receipt = await send_transaction(
        src_w3,
        deployer,
        to=stack.composer_addr,
        data=calldata,
        gas=900_000,
    )
    assert receipt["status"] == 1
    events = await observe_send_packets(
        src_w3,
        stack.src_router,
        stack.src_router_addr,
        from_block=receipt["blockNumber"],
        to_block=receipt["blockNumber"],
    )
    assert len(events) == 1, "composer didn't reach the router"
    packet = events[0]["packet"]
    return packet, int(packet["sequence"])


class _V3PoolDesc(BasePool):
    """Wraps a deployed ``MockV3Pool`` for pydefi's swap lowering."""

    protocol = SwapProtocol.UNISWAP_V3
    fee_bps = 30

    def __init__(self, address: HexBytes, token_in: Token, token1: HexBytes) -> None:
        self.pool_address = address
        self.token_in = token_in
        self._token1 = token1

    def zero_for_one(self, token_out: HexBytes) -> bool:
        return HexBytes(token_out) == self._token1


@dataclass
class _PydefiPieces:
    """DeFiVM + EurekaComposer + MockV3Pool deployed on one chain, pre-funded."""

    defivm: Contract
    defivm_addr: ChecksumAddress
    composer: Contract
    composer_addr: ChecksumAddress
    v3_pool: BasePool
    weth_token: Token
    usdc_token: Token
    usdc_token_dst: Token


async def _deploy_pydefi(
    w3: AsyncWeb3,
    deployer: BaseAccount,
    *,
    test_erc20_addr: ChecksumAddress,
    transfer_addr: ChecksumAddress,
) -> _PydefiPieces:
    """Deploy DeFiVM (patched interpreter) + WETH/MockV3Pool + EurekaComposer on a
    chain, pre-funding DeFiVM with both TestERC20s (``test_erc20_addr`` = USDC)."""
    # Patched interpreter (rejects SLOAD/SSTORE/CALLCODE/DELEGATECALL/SELFDESTRUCT,
    # pydefi #138). Pass the address explicitly: address(0) resolves to the
    # canonical PATCHED_INTERPRETER_ADDRESS, absent on this chain.
    interpreter_addr = await _deploy(
        w3, deployer, compile_pydefi_contract("PatchedInterpreter")
    )
    defivm_async = await build_and_deploy_contract_async(
        w3, "DeFiVM", args=(interpreter_addr,)
    )
    defivm, defivm_addr = Contract(defivm_async.abi), defivm_async.address
    await ERC20.fns.transfer(defivm_addr, _FUND_AMOUNT).transact(
        w3, deployer, to=test_erc20_addr
    )

    weth_addr = await _deploy(w3, deployer, get_contract("TestERC20"))
    pool_addr = await _deploy(
        w3,
        deployer,
        compile_inline(MOCK_V3_POOL_SOL, "MockV3Pool"),
        weth_addr,
        test_erc20_addr,
        1,
        1,
    )
    test_erc20 = Contract(get_contract("TestERC20")["abi"])
    await test_erc20.fns.mint(defivm_addr, _FUND_AMOUNT).transact(
        w3, deployer, to=weth_addr
    )

    composer_art = compile_pydefi_contract("EurekaComposer")
    composer_addr = await _deploy(
        w3, deployer, composer_art, transfer_addr, interpreter_addr
    )

    chain_id = await w3.eth.chain_id
    weth_token = Token(
        chain_id=chain_id, address=HexBytes(weth_addr), symbol="WETH", decimals=18
    )
    usdc_token = Token(
        chain_id=chain_id, address=HexBytes(test_erc20_addr), symbol="USDC", decimals=18
    )
    # Destination Token is only used by RouteDAG for branch tracking.
    usdc_token_dst = Token(
        chain_id=ChainId.MANTRA,
        address=HexBytes(b"\xab" * 20),
        symbol="USDC",
        decimals=18,
    )
    return _PydefiPieces(
        defivm=defivm,
        defivm_addr=defivm_addr,
        composer=Contract(composer_art["abi"]),
        composer_addr=composer_addr,
        v3_pool=_V3PoolDesc(HexBytes(pool_addr), weth_token, HexBytes(test_erc20_addr)),
        weth_token=weth_token,
        usdc_token=usdc_token,
        usdc_token_dst=usdc_token_dst,
    )


@pytest.fixture(scope="module")
async def eureka_stack(mantra) -> EurekaStack:
    """Deploy the Eureka stack + DeFiVM + a MockV3Pool on the ``mantra`` chain,
    pre-funded so DeFiVM has enough USDC and WETH to drive the test flows.

    These tests target pydefi's own contracts (``DeFiVM``, the patched
    interpreter, ``EurekaComposer``, ``Program``/DAG lowering). The single-chain
    ``DummyLightClient`` setup deliberately stubs out the upstream IBC transport
    so contract behavior can be asserted with fast, direct on-chain calls; the
    real transport is exercised by :func:`paired_eureka_stack`."""
    w3 = mantra.async_w3
    deployer = Account.from_key(KEYS["community"])
    stack = await deploy_eureka_stack(w3, KEYS["community"])

    # Wrap the deploy_eureka_stack handles as address-less eth_contract Contracts.
    router = Contract(stack.ics26_router.abi)
    router_addr = stack.ics26_router.address
    transfer = Contract(stack.ics20_transfer.abi)
    transfer_addr = stack.ics20_transfer.address
    test_erc20_addr = stack.test_erc20.address

    p = await _deploy_pydefi(
        w3, deployer, test_erc20_addr=test_erc20_addr, transfer_addr=transfer_addr
    )

    return EurekaStack(
        src_w3=w3,
        dst_w3=w3,
        src_router=router,
        src_router_addr=router_addr,
        src_transfer=transfer,
        src_transfer_addr=transfer_addr,
        defivm=p.defivm,
        defivm_addr=p.defivm_addr,
        test_erc20_addr=test_erc20_addr,
        src_client_id=stack.client_id,
        dst_client_id=stack.counterparty_client_id,
        relayer=_LocalRelayer(w3, router, router_addr, deployer),
        composer=p.composer,
        composer_addr=p.composer_addr,
        light_client=Contract(stack.light_client.abi),
        light_client_addr=stack.light_client.address,
        v3_pool=p.v3_pool,
        weth_token=p.weth_token,
        usdc_token=p.usdc_token,
        usdc_token_dst=p.usdc_token_dst,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_eureka_basic_transfer(eureka_stack):
    """DeFiVM Program does ``approve + ICS20Transfer.sendTransfer`` atomically.
    Assert (a) DeFiVM dropped ``send_amt``, (b) the per-client escrow received
    it, (c) the SendPacket event carries the expected FungibleTokenPacketData,
    and (d) the sequence is 1 (first send through this client)."""
    src_w3 = eureka_stack.src_w3
    deployer = ACCOUNTS["community"]
    send_amt = 10**18
    receiver = eth_to_bech32(ADDRS["signer2"])

    bridge = Eureka(
        src_chain_id=await src_w3.eth.chain_id,
        dst_chain_id=0,
        ics20_transfer_addr=HexBytes(eureka_stack.src_transfer_addr),
        source_client_id=eureka_stack.src_client_id,
    )
    assert bridge.protocol_name == "Eureka"

    bal_before = await ERC20.fns.balanceOf(eureka_stack.defivm_addr).call(
        src_w3, to=eureka_stack.test_erc20_addr
    )

    prog = Program()
    ok = approve_then_send_transfer(
        prog,
        transfer_addr=HexBytes(eureka_stack.src_transfer_addr),
        denom=HexBytes(eureka_stack.test_erc20_addr),
        amount=send_amt,
        receiver=receiver,
        source_client=eureka_stack.src_client_id,
        timeout_seconds=600,
    )
    # Without this, a silent sendTransfer revert leaves the program ending
    # with success=0 on the stack while DELEGATECALL returns true to the
    # outer execute(). Force the failure to surface.
    prog.assert_(ok, "sendTransfer failed")
    prog.builder.stop()

    receipt = await eureka_stack.defivm.fns.execute(prog.build()).transact(
        src_w3, deployer, to=eureka_stack.defivm_addr
    )
    assert receipt["status"] == 1

    bal_after = await ERC20.fns.balanceOf(eureka_stack.defivm_addr).call(
        src_w3, to=eureka_stack.test_erc20_addr
    )
    assert bal_before - bal_after == send_amt

    # Escrow must hold the bridged tokens — proves the source-side state landed.
    escrow_addr = await eureka_stack.src_transfer.fns.getEscrow(
        eureka_stack.src_client_id
    ).call(src_w3, to=eureka_stack.src_transfer_addr)
    escrow_bal = await ERC20.fns.balanceOf(escrow_addr).call(
        src_w3, to=eureka_stack.test_erc20_addr
    )
    assert escrow_bal == send_amt

    events = await observe_send_packets(
        src_w3,
        eureka_stack.src_router,
        eureka_stack.src_router_addr,
        from_block=receipt["blockNumber"],
        to_block=receipt["blockNumber"],
    )
    assert len(events) == 1, "router didn't accept the packet"
    ev = events[0]
    assert int(ev["sequence"]) == 1, "first send on this client must have sequence 1"

    packet = ev["packet"]
    assert packet["sourceClient"] == eureka_stack.src_client_id
    assert len(packet["payloads"]) == 1
    payload = packet["payloads"][0]
    assert payload["sourcePort"] == ICS20_DEFAULT_PORT
    assert payload["destPort"] == ICS20_DEFAULT_PORT

    ((denom, sender, recv, amount, memo),) = abi_decode(
        ["(string,string,string,uint256,string)"],
        bytes(payload["value"]),
    )
    # ICS20Transfer encodes addresses via Strings.toHexString (lowercase 0x...).
    assert int(denom, 16) == int(eureka_stack.test_erc20_addr, 16)
    assert int(sender, 16) == int(eureka_stack.defivm_addr, 16)
    assert recv == receiver
    assert amount == send_amt
    assert memo == ""


async def test_eureka_swap_then_bridge(eureka_stack):
    """One atomic Program: swap WETH→USDC on the local MockV3Pool, then
    ``sendTransfer`` of the USDC out via the bridge edge."""
    deployer = ACCOUNTS["community"]
    src_w3 = eureka_stack.src_w3
    amount_in = 10**18

    weth_addr = eureka_stack.weth_token.address
    usdc_addr = eureka_stack.test_erc20_addr
    weth_before = await ERC20.fns.balanceOf(eureka_stack.defivm_addr).call(
        src_w3, to=weth_addr
    )
    usdc_before = await ERC20.fns.balanceOf(eureka_stack.defivm_addr).call(
        src_w3, to=usdc_addr
    )

    dag = (
        RouteDAG()
        .from_token(eureka_stack.weth_token)
        .swap(eureka_stack.usdc_token, eureka_stack.v3_pool)
        .bridge(
            eureka_stack.usdc_token_dst,
            transfer_addr=HexBytes(eureka_stack.src_transfer_addr),
            source_client=eureka_stack.src_client_id,
            receiver=eth_to_bech32(ADDRS["signer2"]),
            timeout_seconds=600,
        )
    )
    prog = build_execution_program_for_dag(
        dag,
        amount_in=amount_in,
        vm_address=eureka_stack.defivm_addr,
        recipient=eureka_stack.defivm_addr,
    )

    receipt = await eureka_stack.defivm.fns.execute(prog.build()).transact(
        src_w3, deployer, to=eureka_stack.defivm_addr
    )
    assert receipt["status"] == 1

    weth_after = await ERC20.fns.balanceOf(eureka_stack.defivm_addr).call(
        src_w3, to=weth_addr
    )
    usdc_after = await ERC20.fns.balanceOf(eureka_stack.defivm_addr).call(
        src_w3, to=usdc_addr
    )
    # WETH drained (sent to pool via callback); USDC nets to zero (swap minted
    # in then bridge sent out at the same amount).
    assert weth_before - weth_after == amount_in
    assert usdc_after == usdc_before

    events = await observe_send_packets(
        src_w3,
        eureka_stack.src_router,
        eureka_stack.src_router_addr,
        from_block=receipt["blockNumber"],
        to_block=receipt["blockNumber"],
    )
    assert events, "bridge didn't reach the router"


async def test_eureka_v3_swap_only(eureka_stack):
    """Regression: run the V3 swap edge through DeFiVM without the bridge,
    asserting the WETH→USDC delta lands in DeFiVM's balances."""
    deployer = ACCOUNTS["community"]
    src_w3 = eureka_stack.src_w3
    amount_in = 10**18

    weth_addr = eureka_stack.weth_token.address
    usdc_addr = eureka_stack.test_erc20_addr
    weth_before = await ERC20.fns.balanceOf(eureka_stack.defivm_addr).call(
        src_w3, to=weth_addr
    )
    usdc_before = await ERC20.fns.balanceOf(eureka_stack.defivm_addr).call(
        src_w3, to=usdc_addr
    )

    dag = (
        RouteDAG()
        .from_token(eureka_stack.weth_token)
        .swap(eureka_stack.usdc_token, eureka_stack.v3_pool)
    )
    prog = build_execution_program_for_dag(
        dag,
        amount_in=amount_in,
        vm_address=eureka_stack.defivm_addr,
        recipient=eureka_stack.defivm_addr,
    )

    receipt = await eureka_stack.defivm.fns.execute(prog.build()).transact(
        src_w3, deployer, to=eureka_stack.defivm_addr
    )
    assert receipt["status"] == 1

    weth_after = await ERC20.fns.balanceOf(eureka_stack.defivm_addr).call(
        src_w3, to=weth_addr
    )
    usdc_after = await ERC20.fns.balanceOf(eureka_stack.defivm_addr).call(
        src_w3, to=usdc_addr
    )
    assert weth_before - weth_after == amount_in
    assert usdc_after - usdc_before == amount_in


async def test_mock_v3_pool_swap_from_eoa(eureka_stack):
    """Regression: ``MockV3Pool.swap`` called directly from an EOA mints the
    output to the recipient. EOAs have no code so the V3 callback returns
    ``ok=true`` with empty data — pool.swap should succeed silently. Guards
    the initial-supply choice in :func:`deploy_eureka_stack` — if it climbs
    back to ``type(uint256).max`` this test catches the Panic 0x11 first."""
    deployer = Account.from_key(KEYS["community"])
    src_w3 = eureka_stack.src_w3
    amount_in = 10**18

    callback_data = abi_encode(["address"], [eureka_stack.weth_token.address])
    swap = _V3_POOL.fns.swap(
        deployer.address,
        True,
        amount_in,
        4295128741,  # > TickMath.MIN_SQRT_RATIO
        callback_data,
    )
    pool_addr = eureka_stack.v3_pool.pool_address

    # eth_call first for a clean revert reason.
    try:
        await swap.call(src_w3, **{"to": pool_addr, "from": deployer.address})
    except Exception as exc:
        pytest.fail(f"pool.swap eth_call reverted: {exc!r}")

    usdc_before = await ERC20.fns.balanceOf(deployer.address).call(
        src_w3, to=eureka_stack.test_erc20_addr
    )
    receipt = await swap.transact(src_w3, deployer, to=pool_addr, gas=500_000)
    assert receipt["status"] == 1
    usdc_after = await ERC20.fns.balanceOf(deployer.address).call(
        src_w3, to=eureka_stack.test_erc20_addr
    )
    assert usdc_after - usdc_before == amount_in


async def test_eureka_ack_callback(eureka_stack):
    """``EurekaComposer.sendTransferAndCompose`` registers a follow-up program
    keyed by ``(sourceClient, sequence)``; then drive ``router.ackPacket``
    directly to fire ``ICS20Transfer.onAcknowledgementPacket →
    IBCSenderCallbacksLib.ackPacketCallback → composer.onAckPacket``, which
    DELEGATECALLs the interpreter with the program and clears the slot.

    Driving the ack without a real relayer works because ``DummyLightClient``
    returns success regardless of proof bytes and ``pubRelay=True`` grants
    ``ackPacket`` to PUBLIC_ROLE.
    """
    assert eureka_stack.composer is not None
    assert eureka_stack.composer_addr is not None
    src_w3 = eureka_stack.src_w3
    deployer = ACCOUNTS["community"]
    amount = 10**18

    iface = await eureka_stack.composer.fns.supportsInterface(
        IIBC_SENDER_CALLBACKS_INTERFACE_ID
    ).call(src_w3, to=eureka_stack.composer_addr)
    assert iface, "EurekaComposer must advertise IIBCSenderCallbacks"

    follow_up = Program()
    follow_up.return_word(follow_up.builder.tload(0))
    program_bytes = follow_up.build()

    packet, sequence = await _compose_and_get_packet(
        eureka_stack,
        deployer,
        amount=amount,
        program_bytes=program_bytes,
        receiver=eth_to_bech32(ADDRS["signer2"]),
    )

    # Program is registered under (sourceClient, sequence).
    stored = await eureka_stack.composer.fns.programs(
        eureka_stack.src_client_id, sequence
    ).call(src_w3, to=eureka_stack.composer_addr)
    assert bytes(stored) == bytes(program_bytes), "program not registered"

    ack_receipt = await eureka_stack.relayer.deliver_ack(packet)

    # Composer cleared the slot after running the program.
    cleared = await eureka_stack.composer.fns.programs(
        eureka_stack.src_client_id, sequence
    ).call(src_w3, to=eureka_stack.composer_addr)
    assert bytes(cleared) == b"", "program not cleared after ack"

    # AckExecuted fired with success=True for SUCCESSFUL_ACKNOWLEDGEMENT_JSON.
    ack_logs = await eureka_stack.composer.events.AckExecuted.get_logs(
        src_w3,
        address=eureka_stack.composer_addr,
        from_block=ack_receipt["blockNumber"],
        to_block=ack_receipt["blockNumber"],
    )
    assert len(ack_logs) == 1
    args = dict(ack_logs[0]["args"])
    assert int(args["sequence"]) == sequence
    assert args["success"] is True


async def test_eureka_timeout_callback(eureka_stack):
    """Drive ``router.timeoutPacket`` directly so ``ICS20Transfer.
    onTimeoutPacket → _refundTokens`` returns the escrowed funds to the
    composer, and ``IBCSenderCallbacksLib.timeoutPacketCallback →
    composer.onTimeoutPacket`` runs the registered program and clears the slot.

    ICS26Router.timeoutPacket requires ``counterpartyTimestamp >=
    packet.timeoutTimestamp``; ``DummyLightClient.verifyNonMembership`` returns
    ``membershipResult`` (initially 0). Bump it to ``uint64.max`` so any
    in-the-future packet timeoutTimestamp passes the check.

    Mutating the light client is fine because no later test in this module
    calls verifyMembership / verifyNonMembership on it.
    """
    assert eureka_stack.composer is not None
    assert eureka_stack.composer_addr is not None
    assert eureka_stack.light_client is not None
    assert eureka_stack.light_client_addr is not None
    src_w3 = eureka_stack.src_w3
    deployer = ACCOUNTS["community"]
    amount = 10**18

    # Bump DummyLightClient.membershipResult so the timeout-elapsed check
    # (counterpartyTimestamp >= packet.timeoutTimestamp) passes for any future
    # timeoutTimestamp the packet might carry.
    await eureka_stack.light_client.fns.setMembershipResult(
        2**64 - 1, False
    ).transact(src_w3, deployer, to=eureka_stack.light_client_addr)

    follow_up = Program()
    follow_up.return_word(follow_up.builder.tload(0))
    program_bytes = follow_up.build()

    composer_bal_before = await ERC20.fns.balanceOf(eureka_stack.composer_addr).call(
        src_w3, to=eureka_stack.test_erc20_addr
    )
    packet, sequence = await _compose_and_get_packet(
        eureka_stack,
        deployer,
        amount=amount,
        program_bytes=program_bytes,
        receiver=eth_to_bech32(ADDRS["signer2"]),
    )

    timeout_receipt = await eureka_stack.relayer.deliver_timeout(packet)

    # Escrow refunded `amount` back to the packet sender — which is the composer.
    composer_bal_after = await ERC20.fns.balanceOf(eureka_stack.composer_addr).call(
        src_w3, to=eureka_stack.test_erc20_addr
    )
    assert composer_bal_after - composer_bal_before == amount

    # Composer's program slot cleared.
    cleared = await eureka_stack.composer.fns.programs(
        eureka_stack.src_client_id, sequence
    ).call(src_w3, to=eureka_stack.composer_addr)
    assert bytes(cleared) == b"", "program not cleared after timeout"

    # TimeoutExecuted fired.
    timeout_logs = await eureka_stack.composer.events.TimeoutExecuted.get_logs(
        src_w3,
        address=eureka_stack.composer_addr,
        from_block=timeout_receipt["blockNumber"],
        to_block=timeout_receipt["blockNumber"],
    )
    assert len(timeout_logs) == 1
    assert int(timeout_logs[0]["args"]["sequence"]) == sequence


@dataclass
class _ChainSide:
    w3: AsyncWeb3
    router: Contract
    router_addr: ChecksumAddress
    transfer: Contract
    transfer_addr: ChecksumAddress
    test_erc20_addr: ChecksumAddress
    light_client_addr: ChecksumAddress
    client_id: str
    deployer: BaseAccount


@dataclass
class PairedEurekaStack:
    src: _ChainSide
    dst: _ChainSide
    attestors: tuple  # (src_attestor, dst_attestor) — each has .stop()
    relayer_process: RelayerProcess
    binary_relayer: BinaryRelayer


_ZERO_ADDR = "0x" + "0" * 40


async def _build_paired_side(
    w3: AsyncWeb3,
    counterparty_client_id: str,
    counterparty_attestor_address: str,
) -> _ChainSide:
    """Deploy one side configured to trust the attestor that watches the
    counterparty chain. ``merkle_prefix=[b""]`` keeps prefixedPath at length
    1 (AttestationLightClient rejects anything else)."""
    deployer = Account.from_key(KEYS["community"])
    # AttestationLightClient ctor: (attestorAddresses, minRequiredSigs,
    # initialHeight, initialTimestampSeconds, roleManager); zero roleManager
    # opens PROOF_SUBMITTER_ROLE to anyone.
    ctor = ([counterparty_attestor_address], 1, 0, 0, _ZERO_ADDR)
    stack = await deploy_eureka_stack(
        w3,
        KEYS["community"],
        counterparty_client_id=counterparty_client_id,
        light_client=("AttestationLightClient", ctor),
        merkle_prefix=[b""],
    )
    return _ChainSide(
        w3=w3,
        router=Contract(stack.ics26_router.abi),
        router_addr=stack.ics26_router.address,
        transfer=Contract(stack.ics20_transfer.abi),
        transfer_addr=stack.ics20_transfer.address,
        test_erc20_addr=stack.test_erc20.address,
        light_client_addr=stack.light_client.address,
        client_id=stack.client_id,
        deployer=deployer,
    )


@pytest.fixture(scope="module")
async def paired_eureka_stack(paired_mantra, tmp_path_factory) -> PairedEurekaStack:
    """Cross-chain Eureka fixture in ``attested`` mode against the real
    ``ibc_attestor`` + ``ibc-eureka-relayer`` binaries.

    Skips if either binary isn't on ``$PATH`` (i.e. when not under
    ``nix develop``).
    """
    from ibc_eureka.harness.attestor import Attestor
    from ibc_eureka.harness.relayer import build_eth_to_eth_config, start_relayer
    from ibc_eureka.relayer.binary import BinaryRelayer, _Endpoint

    from .utils import free_port

    src_mantra, dst_mantra = paired_mantra

    # Keygen first: each chain's light client tracks the counterparty, so it
    # must be initialised with the OTHER chain's attestor address.
    src_attestor = Attestor(tmp_path_factory.mktemp("attestor_src"))
    dst_attestor = Attestor(tmp_path_factory.mktemp("attestor_dst"))

    src = await _build_paired_side(
        src_mantra.async_w3,
        counterparty_client_id="client-0",
        counterparty_attestor_address=dst_attestor.address,
    )
    dst = await _build_paired_side(
        dst_mantra.async_w3,
        counterparty_client_id="client-0",
        counterparty_attestor_address=src_attestor.address,
    )

    # Attestors now know their ICS26Router targets — spawn them.
    src_attestor.start(
        rpc_url=src_mantra.w3_http_endpoint(),
        router_address=src.router_addr,
    )
    dst_attestor.start(
        rpc_url=dst_mantra.w3_http_endpoint(),
        router_address=dst.router_addr,
    )

    src_chain_id = hex(await src.w3.eth.chain_id)
    dst_chain_id = hex(await dst.w3.eth.chain_id)
    config = build_eth_to_eth_config(
        grpc_port=free_port(),
        grpc_web_port=free_port(),
        src_chain_id=src_chain_id,
        src_rpc_url=src_mantra.w3_http_endpoint(),
        src_ics26_address=src.router_addr,
        src_attestor_endpoint=src_attestor.grpc_endpoint,
        dst_chain_id=dst_chain_id,
        dst_rpc_url=dst_mantra.w3_http_endpoint(),
        dst_ics26_address=dst.router_addr,
        dst_attestor_endpoint=dst_attestor.grpc_endpoint,
    )
    work_dir = tmp_path_factory.mktemp("eureka_relayer")
    relayer_process = start_relayer(config, work_dir=work_dir)

    binary_relayer = BinaryRelayer(
        src=_Endpoint(
            w3=src.w3,
            router_addr=src.router_addr,
            client_id=src.client_id,
            chain_id=src_chain_id,
            deployer=src.deployer,
        ),
        dst=_Endpoint(
            w3=dst.w3,
            router_addr=dst.router_addr,
            client_id=dst.client_id,
            chain_id=dst_chain_id,
            deployer=dst.deployer,
        ),
        grpc_address=relayer_process.grpc_address,
    )

    try:
        yield PairedEurekaStack(
            src=src,
            dst=dst,
            attestors=(src_attestor, dst_attestor),
            relayer_process=relayer_process,
            binary_relayer=binary_relayer,
        )
    finally:
        binary_relayer.close()
        relayer_process.stop()
        src_attestor.stop()
        dst_attestor.stop()


async def test_eureka_cross_chain_transfer_via_binary(paired_eureka_stack):
    """A → B → A round-trip via the upstream ibc-eureka-relayer:
    sendTransfer, relay src→dst (IBCERC20 mint), relay dst→src (ack).
    Asserts source escrow + dst receiver balances."""
    stack = paired_eureka_stack
    src, dst, relayer = stack.src, stack.dst, stack.binary_relayer

    receiver_hex = HexBytes(ADDRS["signer2"]).to_0x_hex()
    amount = 10**18

    # Approve + sendTransfer on src.
    await ERC20.fns.approve(src.transfer_addr, amount).transact(
        src.w3, src.deployer, to=src.test_erc20_addr
    )
    calldata = encode_send_transfer_calldata(
        denom=HexBytes(src.test_erc20_addr),
        amount=amount,
        receiver=receiver_hex,
        source_client=src.client_id,
        timeout_timestamp=int(time.time()) + 600,
    )
    send_receipt = await send_transaction(
        src.w3, src.deployer, to=src.transfer_addr, data=calldata, gas=900_000
    )
    assert send_receipt["status"] == 1

    # Relay src→dst (recvPacket + IBCERC20 mint) then dst→src (ackPacket).
    # Each RelayByTx response is a multicall that bundles updateClient with
    # the recvPacket/ackPacket so we don't need explicit updateClient calls.
    recv_receipt = await relayer.relay(
        relayer.src, relayer.dst, bytes(send_receipt["transactionHash"])
    )
    await relayer.relay(
        relayer.dst, relayer.src, bytes(recv_receipt["transactionHash"])
    )

    # Source escrow holds the original TestERC20.
    escrow_addr = await src.transfer.fns.getEscrow(src.client_id).call(
        src.w3, to=src.transfer_addr
    )
    src_escrow_bal = await ERC20.fns.balanceOf(escrow_addr).call(
        src.w3, to=src.test_erc20_addr
    )
    assert src_escrow_bal == amount

    # Destination has an IBCERC20 minted to the receiver.
    denom_path = (
        f"transfer/{dst.client_id}/"
        + "0x"
        + bytes(HexBytes(src.test_erc20_addr)).hex().lower()
    )
    ibc_erc20_addr = await dst.transfer.fns.ibcERC20Contract(denom_path).call(
        dst.w3, to=dst.transfer_addr
    )
    # ICS20Transfer's getter returns a lowercase address
    receiver_bal = await ERC20.fns.balanceOf(HexBytes(ADDRS["signer2"])).call(
        dst.w3, to=to_checksum_address(ibc_erc20_addr)
    )
    assert receiver_bal == amount


async def test_eureka_contracts_compile():
    """Compile every contract in ``CONTRACTS`` from the upstream source tree.
    Catches upstream-source drift before the deploy fixture even spins up."""
    from .eureka_artifacts import CONTRACTS

    for name in CONTRACTS:
        art = get_contract(name)
        assert art["abi"], f"{name}: empty ABI"
        assert art["bin"], f"{name}: empty bytecode"


async def test_eureka_stack_deploy_smoke(mantra):
    """Deploy the full Eureka stack via :func:`deploy_eureka_stack` and assert
    each component is live + the router knows about the transfer app."""
    w3 = mantra.async_w3
    stack = await deploy_eureka_stack(w3, KEYS["community"])

    for label, addr in (
        ("AccessManager", stack.access_manager.address),
        ("ICS26Router", stack.ics26_router.address),
        ("ICS20Transfer", stack.ics20_transfer.address),
        ("TestERC20", stack.test_erc20.address),
        ("DummyLightClient", stack.light_client.address),
    ):
        code = await w3.eth.get_code(addr)
        assert len(code) > 0, f"{label}: no runtime code"

    router = Contract(stack.ics26_router.abi)
    registered = await router.fns.getIBCApp(ICS20_DEFAULT_PORT).call(
        w3, to=stack.ics26_router.address
    )
    assert to_checksum_address(registered) == to_checksum_address(
        stack.ics20_transfer.address
    )

    assert stack.client_id

    # Round-trip the counterparty + light-client wiring: addClient registered
    # both during deploy_eureka_stack; the router must echo them back.
    counterparty = await router.fns.getCounterparty(stack.client_id).call(
        w3, to=stack.ics26_router.address
    )
    assert counterparty[0] == stack.counterparty_client_id
    assert [bytes(b) for b in counterparty[1]] == [b"ibc", b""]

    bound_client = await router.fns.getClient(stack.client_id).call(
        w3, to=stack.ics26_router.address
    )
    assert to_checksum_address(bound_client) == to_checksum_address(
        stack.light_client.address
    )
    # Initial mint is capped at 10**30 so MockV3Pool can still .mint() into
    # the same TestERC20 without overflowing _totalSupply (see eureka_deploy.py).
    bal = await ERC20.fns.balanceOf(stack.deployer.address).call(
        w3, to=stack.test_erc20.address
    )
    assert bal == 10**30


# ---------------------------------------------------------------------------
# EVM → Cosmos: exercise evmd's Cosmos-side IBC v2 router (ibcRouterV2)
# ---------------------------------------------------------------------------
#
# Topology (fully attested, no SP1): the paired_mantra ``src`` chain hosts the
# solidity-ibc-eureka stack on its EVM layer and is the packet SOURCE; the
# ``dst`` chain (evmd) is the Cosmos DESTINATION whose ibcRouterV2 →
# transferStackV2 receives the packet and mints the voucher. One attestor
# watches the EVM source (recv leg), one watches the Cosmos dest (ack leg);
# the EVM side trusts the cosmos-watching attestor via AttestationLightClient,
# evmd trusts the EVM-watching attestor via the ibc-go ``attestations`` client.


@dataclass
class EthToCosmosEurekaStack:
    eth_w3: AsyncWeb3
    eth_transfer: Contract  # ICS20Transfer ABI wrapper (for getEscrow)
    eth_transfer_addr: ChecksumAddress
    eth_test_erc20_addr: ChecksumAddress
    eth_router_addr: ChecksumAddress
    eth_client_id: str  # EVM source client (sendTransfer sourceClient)
    eth_chain_id: str  # hex "0x…"
    dst_mantra: Any  # cosmos destination (evmd) — has .cosmos_cli()
    cosmos_chain_id: str  # cosmos chain-id string (relayer src/dst identifier)
    cosmos_client_id: str  # attestations-0
    cosmos_ep: _Endpoint  # carries the cosmos chain-id + client-id (ack src)
    relayer_signer: str  # cosmos submitter key name
    denom: str  # cosmos fee/bond denom (atest)
    relayer: BinaryRelayer  # .src is the EVM endpoint / ack dest
    attestors: tuple  # (eth_attestor, cosmos_attestor)
    relayer_process: RelayerProcess


@pytest.fixture(scope="module")
async def eth_to_cosmos_eureka_stack(paired_mantra, tmp_path_factory):
    """EVM→Cosmos attested Eureka fixture. Skips when ``ibc_attestor`` /
    ``relayer`` aren't on ``$PATH`` (i.e. outside ``nix develop``)."""
    from ibc_eureka.harness.attestor import Attestor
    from ibc_eureka.harness.relayer import build_eth_to_cosmos_config, start_relayer
    from ibc_eureka.relayer.binary import BinaryRelayer, _Endpoint
    from pystarport import ports

    from .utils import free_port

    src_mantra, dst_mantra = paired_mantra  # src = EVM source, dst = cosmos dest
    eth_w3 = src_mantra.async_w3
    eth_deployer = Account.from_key(KEYS["community"])
    relayer_signer = "signer1"  # funded cosmos submitter on the dst chain
    denom = dst_mantra.cosmos_cli().get_params("staking")["bond_denom"]
    cosmos_chain_id = dst_mantra.cosmos_cli().chain_id
    cosmos_rpc = f"http://127.0.0.1:{ports.rpc_port(dst_mantra.base_port(0))}"

    # Keygen first — the EVM light client must be initialised trusting the
    # cosmos-watching attestor's address.
    eth_attestor = Attestor(tmp_path_factory.mktemp("att_eth"))
    cosmos_attestor = Attestor(tmp_path_factory.mktemp("att_cosmos"))

    # EVM source stack. AttestationLightClient (tracking the cosmos chain, used
    # for the ack + return-recv legs) trusts the cosmos attestor; the
    # counterparty is the cosmos client — deterministically "attestations-0" on
    # a fresh evmd. merkle_prefix=[b""] keeps the verifyMembership path length 1
    # (AttestationLightClient.sol requires exactly 1; it signs over keccak256(
    # path[0]) rather than doing a real merkle proof, so the cosmos "ibc" store
    # prefix is irrelevant). Same as _build_paired_side.
    cosmos_client_id = "attestations-0"
    ctor = ([cosmos_attestor.address], 1, 0, 0, _ZERO_ADDR)
    eth_stack = await deploy_eureka_stack(
        eth_w3,
        KEYS["community"],
        counterparty_client_id=cosmos_client_id,
        light_client=("AttestationLightClient", ctor),
        merkle_prefix=[b""],
    )
    eth_client_id = eth_stack.client_id  # e.g. "client-0"
    eth_chain_id = hex(await eth_w3.eth.chain_id)

    eth_attestor.start(
        rpc_url=src_mantra.w3_http_endpoint(),
        router_address=eth_stack.ics26_router.address,
        chain_type="evm",
    )
    cosmos_attestor.start(rpc_url=cosmos_rpc, chain_type="cosmos")

    config = build_eth_to_cosmos_config(
        grpc_port=free_port(),
        grpc_web_port=free_port(),
        eth_chain_id=eth_chain_id,
        eth_rpc_url=src_mantra.w3_http_endpoint(),
        eth_ics26_address=eth_stack.ics26_router.address,
        eth_attestor_endpoint=eth_attestor.grpc_endpoint,
        cosmos_chain_id=cosmos_chain_id,
        cosmos_rpc_url=cosmos_rpc,
        cosmos_signer_address=dst_mantra.cosmos_cli().address(relayer_signer),
        cosmos_attestor_endpoint=cosmos_attestor.grpc_endpoint,
    )
    work_dir = tmp_path_factory.mktemp("eth_to_cosmos_relayer")
    relayer_process = start_relayer(config, work_dir=work_dir)

    # relay_to_cosmos doesn't read .src/.dst; pass the EVM endpoint for both.
    eth_ep = _Endpoint(
        w3=eth_w3,
        router_addr=eth_stack.ics26_router.address,
        client_id=eth_client_id,
        chain_id=eth_chain_id,
        deployer=eth_deployer,
    )
    # Ack leg source: relay() only reads from_side.chain_id + .client_id, so a
    # cosmos-flavored endpoint suffices (w3/router/deployer go unused).
    cosmos_ep = _Endpoint(
        w3=eth_w3,
        router_addr=eth_stack.ics26_router.address,
        client_id=cosmos_client_id,
        chain_id=cosmos_chain_id,
        deployer=eth_deployer,
    )
    relayer = BinaryRelayer(
        src=eth_ep, dst=eth_ep, grpc_address=relayer_process.grpc_address
    )

    # Create the cosmos attestations client tracking the EVM chain, then wire
    # the v2 counterparty both ways: cosmos attestations-0 ↔ EVM client.
    eth_block = await eth_w3.eth.get_block("latest")
    created = relayer.create_attestations_client(
        eth_chain_id=eth_chain_id,
        cosmos_chain_id=cosmos_chain_id,
        attestor_addresses=[eth_attestor.address],
        height=eth_block["number"],
        timestamp=eth_block["timestamp"],
        cosmos_signer=cosmos_signer(dst_mantra, relayer_signer, denom=denom),
    )
    assert created == cosmos_client_id, f"expected {cosmos_client_id}, got {created}"
    # EVM commitment prefix is a single empty element (matches _build_paired_side).
    dst_mantra.cosmos_cli().ibc_client_add_counterparty(
        cosmos_client_id, eth_client_id, [b""], from_=relayer_signer, denom=denom
    )

    try:
        yield EthToCosmosEurekaStack(
            eth_w3=eth_w3,
            eth_transfer=Contract(eth_stack.ics20_transfer.abi),
            eth_transfer_addr=eth_stack.ics20_transfer.address,
            eth_test_erc20_addr=eth_stack.test_erc20.address,
            eth_router_addr=eth_stack.ics26_router.address,
            eth_client_id=eth_client_id,
            eth_chain_id=eth_chain_id,
            dst_mantra=dst_mantra,
            cosmos_chain_id=cosmos_chain_id,
            cosmos_client_id=cosmos_client_id,
            cosmos_ep=cosmos_ep,
            relayer_signer=relayer_signer,
            denom=denom,
            relayer=relayer,
            attestors=(eth_attestor, cosmos_attestor),
            relayer_process=relayer_process,
        )
    finally:
        relayer.close()
        relayer_process.stop()
        eth_attestor.stop()
        cosmos_attestor.stop()


def _cosmos_addr(stack, name: str) -> str:
    """Cosmos-side bech32 address for keyring ``name`` on the dst chain."""
    return stack.dst_mantra.cosmos_cli().address(name)


def _relay_recv_ack(stack, tx_hash: bytes) -> dict:
    """Relay an EVM recv/ack tx onto the cosmos chain (eth->cosmos module)."""
    return stack.relayer.relay_to_cosmos(
        src_chain=stack.eth_chain_id,
        dst_chain=stack.cosmos_chain_id,
        src_client_id=stack.eth_client_id,
        dst_client_id=stack.cosmos_client_id,
        tx_hash=tx_hash,
        cosmos_signer=cosmos_signer(
            stack.dst_mantra, stack.relayer_signer, denom=stack.denom
        ),
    )


async def _eth_to_cosmos_send(
    stack, *, receiver: str, amount: int, timeout_secs: int = 600
):
    """approve + ICS20 sendTransfer a TestERC20 from the EVM source; return receipt."""
    deployer = Account.from_key(KEYS["community"])
    await ERC20.fns.approve(stack.eth_transfer_addr, amount).transact(
        stack.eth_w3, deployer, to=stack.eth_test_erc20_addr
    )
    calldata = encode_send_transfer_calldata(
        denom=HexBytes(stack.eth_test_erc20_addr),
        amount=amount,
        receiver=receiver,
        source_client=stack.eth_client_id,
        timeout_timestamp=int(time.time()) + timeout_secs,
    )
    receipt = await send_transaction(
        stack.eth_w3, deployer, to=stack.eth_transfer_addr, data=calldata, gas=900_000
    )
    assert receipt["status"] == 1
    return receipt


async def _mint_voucher(stack, holder: str, amount: int) -> tuple[str, int]:
    """Forward EVM->Cosmos + relay the recv so ``holder`` gets a fresh voucher.
    Returns ``(voucher_denom, balance)``."""
    before = ibc_voucher_balances(stack.dst_mantra, holder)
    receipt = await _eth_to_cosmos_send(stack, receiver=holder, amount=amount)
    _relay_recv_ack(stack, bytes(receipt["transactionHash"]))
    after = ibc_voucher_balances(stack.dst_mantra, holder)
    voucher = next(d for d in after if after[d] - before.get(d, 0) >= amount)
    return voucher, after[voucher]


async def test_eureka_eth_to_cosmos_via_router_v2(eth_to_cosmos_eureka_stack):
    """EVM sendTransfer relayed into evmd: ibcRouterV2 mints an IBC voucher to the
    cosmos receiver; the ack leg back to EVM keeps the source escrow funded."""
    stack = eth_to_cosmos_eureka_stack
    eth_w3 = stack.eth_w3
    amount = 10**18
    receiver = _cosmos_addr(stack, "signer2")
    before = ibc_voucher_balances(stack.dst_mantra, receiver)

    send_receipt = await _eth_to_cosmos_send(stack, receiver=receiver, amount=amount)
    recv_tx = _relay_recv_ack(stack, bytes(send_receipt["transactionHash"]))
    assert recv_tx["code"] == 0, recv_tx.get("raw_log")
    # ibcRouterV2 routed a channel-v2 recv to the transfer app.
    assert any(
        ev["type"] in ("recv_packet", "write_acknowledgement", "fungible_token_packet")
        for ev in recv_tx.get("events", [])
    ), "no v2 recv/transfer event"

    after = ibc_voucher_balances(stack.dst_mantra, receiver)
    assert any(
        after[d] - before.get(d, 0) == amount for d in after
    ), "voucher not minted"

    # Ack leg: relay evmd's write_acknowledgement back to the EVM ICS26Router
    # (updateClient + ackPacket), finalizing the source transfer.
    ack_receipt = await stack.relayer.relay(
        stack.cosmos_ep, stack.relayer.src, bytes.fromhex(recv_tx["txhash"])
    )
    assert ack_receipt["status"] == 1

    # Acked (not refunded): escrow still holds the funds.
    escrow = await stack.eth_transfer.fns.getEscrow(stack.eth_client_id).call(
        eth_w3, to=stack.eth_transfer_addr
    )
    escrow_bal = await ERC20.fns.balanceOf(escrow).call(
        eth_w3, to=stack.eth_test_erc20_addr
    )
    assert escrow_bal == amount


async def test_eureka_cosmos_to_eth_return_via_router_v2(eth_to_cosmos_eureka_stack):
    """Cosmos→EVM return: mint a voucher (forward leg), send it back via an
    ABI-encoded ICS20 v2 ``MsgTransfer``; relaying the recv releases the escrowed
    TestERC20 to the EVM receiver and the ack back to cosmos clears the
    commitment. Self-contained (does its own forward mint)."""
    stack = eth_to_cosmos_eureka_stack
    eth_w3 = stack.eth_w3
    amount = 10**18
    holder = _cosmos_addr(stack, "signer2")
    voucher, voucher_before = await _mint_voucher(stack, holder, amount)

    eth_receiver = ADDRS["signer1"]  # holds 0 TestERC20 → clean delta
    recv_before = await ERC20.fns.balanceOf(eth_receiver).call(
        eth_w3, to=stack.eth_test_erc20_addr
    )
    escrow = await stack.eth_transfer.fns.getEscrow(stack.eth_client_id).call(
        eth_w3, to=stack.eth_transfer_addr
    )
    escrow_before = await ERC20.fns.balanceOf(escrow).call(
        eth_w3, to=stack.eth_test_erc20_addr
    )

    cosmos_send = send_v2_transfer(
        stack.dst_mantra,
        "signer2",
        source_client=stack.cosmos_client_id,
        receiver=eth_receiver,
        token_denom=voucher,
        amount=amount,
        timeout_timestamp=int(time.time()) + 600,
        fee_denom=stack.denom,
    )
    assert cosmos_send["code"] == 0, cosmos_send.get("raw_log")
    burned = ibc_voucher_balances(stack.dst_mantra, holder).get(voucher, 0)
    assert burned == voucher_before - amount, "send should burn the voucher"

    return_recv = await stack.relayer.relay(
        stack.cosmos_ep, stack.relayer.src, bytes.fromhex(cosmos_send["txhash"])
    )
    assert return_recv["status"] == 1
    # Ack back to cosmos clears the cosmos packet commitment (lifecycle complete).
    assert _relay_recv_ack(stack, bytes(return_recv["transactionHash"]))["code"] == 0

    # EVM receiver got the original TestERC20 back; escrow released exactly it.
    recv_after = await ERC20.fns.balanceOf(eth_receiver).call(
        eth_w3, to=stack.eth_test_erc20_addr
    )
    escrow_after = await ERC20.fns.balanceOf(escrow).call(
        eth_w3, to=stack.eth_test_erc20_addr
    )
    assert recv_after - recv_before == amount
    assert escrow_before - escrow_after == amount


async def test_eureka_eth_to_cosmos_error_ack_refund(eth_to_cosmos_eureka_stack):
    """Failure branch: a transfer whose cosmos recv fails (invalid receiver) makes
    evmd write a universal error ack; relaying it back to EVM refunds the sender."""
    stack = eth_to_cosmos_eureka_stack
    eth_w3 = stack.eth_w3
    deployer = Account.from_key(KEYS["community"])
    amount = 10**18

    sender_before = await ERC20.fns.balanceOf(deployer.address).call(
        eth_w3, to=stack.eth_test_erc20_addr
    )
    # An unparseable receiver fails the cosmos transfer app's OnRecvPacket, so
    # evmd commits a success-tx that writes the universal error ack.
    send_receipt = await _eth_to_cosmos_send(
        stack, receiver="notanaddress", amount=amount
    )
    recv_tx = _relay_recv_ack(stack, bytes(send_receipt["transactionHash"]))
    assert recv_tx["code"] == 0, recv_tx.get("raw_log")

    # Relay the error ack back → EVM refunds the sender.
    ack = await stack.relayer.relay(
        stack.cosmos_ep, stack.relayer.src, bytes.fromhex(recv_tx["txhash"])
    )
    assert ack["status"] == 1

    sender_after = await ERC20.fns.balanceOf(deployer.address).call(
        eth_w3, to=stack.eth_test_erc20_addr
    )
    assert sender_after == sender_before, "error ack should refund the sender"


async def test_eureka_eth_to_cosmos_timeout_refund(eth_to_cosmos_eureka_stack):
    """Failure branch: send with a short timeout, never relay the recv, then relay
    a timeout (cosmos non-receipt proof) to the EVM source → refund."""
    stack = eth_to_cosmos_eureka_stack
    eth_w3 = stack.eth_w3
    deployer = Account.from_key(KEYS["community"])
    amount = 10**18

    sender_before = await ERC20.fns.balanceOf(deployer.address).call(
        eth_w3, to=stack.eth_test_erc20_addr
    )
    send_receipt = await _eth_to_cosmos_send(
        stack, receiver=_cosmos_addr(stack, "signer2"), amount=amount, timeout_secs=8
    )

    # Do NOT relay the recv. Wait past the timeout and let the cosmos chain
    # advance so the attestor can attest non-receipt at a height beyond it.
    await asyncio.sleep(12)
    wait_for_new_blocks(stack.dst_mantra.cosmos_cli(), 2)

    timeout_receipt = await stack.relayer.relay_timeout(
        src_chain=stack.cosmos_chain_id,
        dst_chain=stack.eth_chain_id,
        src_client_id=stack.cosmos_client_id,
        dst_client_id=stack.eth_client_id,
        timeout_tx_hash=bytes(send_receipt["transactionHash"]),
        to_side=stack.relayer.src,
    )
    assert timeout_receipt["status"] == 1

    sender_after = await ERC20.fns.balanceOf(deployer.address).call(
        eth_w3, to=stack.eth_test_erc20_addr
    )
    assert sender_after == sender_before, "timeout should refund the sender"


async def test_eureka_cosmos_to_eth_return_error_ack_refund(eth_to_cosmos_eureka_stack):
    """Failure branch (cosmos source): return a voucher with ``receiver=0x0`` so
    the EVM escrow release reverts and the router writes a universal error ack
    (recv tx still succeeds); relaying it back to cosmos re-mints the burned
    voucher to the sender."""
    stack = eth_to_cosmos_eureka_stack
    amount = 10**18
    holder = _cosmos_addr(stack, "signer2")
    voucher, voucher_before = await _mint_voucher(stack, holder, amount)

    # Return to the ZERO address → EVM escrow release reverts → error ack.
    cosmos_send = send_v2_transfer(
        stack.dst_mantra,
        "signer2",
        source_client=stack.cosmos_client_id,
        receiver="0x" + "0" * 40,
        token_denom=voucher,
        amount=amount,
        timeout_timestamp=int(time.time()) + 600,
        fee_denom=stack.denom,
    )
    assert cosmos_send["code"] == 0, cosmos_send.get("raw_log")
    burned = ibc_voucher_balances(stack.dst_mantra, holder).get(voucher, 0)
    assert burned == voucher_before - amount, "send should burn the voucher"

    err_recv = await stack.relayer.relay(
        stack.cosmos_ep, stack.relayer.src, bytes.fromhex(cosmos_send["txhash"])
    )
    assert err_recv["status"] == 1  # error ack committed, tx not reverted
    # Relay the error ack back to cosmos → ibcRouterV2 refunds the voucher.
    assert _relay_recv_ack(stack, bytes(err_recv["transactionHash"]))["code"] == 0

    refunded = ibc_voucher_balances(stack.dst_mantra, holder).get(voucher, 0)
    assert refunded == voucher_before, "error ack should refund the voucher"


async def test_eureka_cosmos_to_eth_return_timeout_refund(eth_to_cosmos_eureka_stack):
    """Failure branch (cosmos source): return a voucher with a short timeout, never
    relay the recv; once the EVM chain advances past the timeout, relaying a cosmos
    ``MsgTimeout`` (non-receipt proven on EVM via the eth→cosmos module) re-mints
    the voucher to the sender."""
    stack = eth_to_cosmos_eureka_stack
    eth_w3 = stack.eth_w3
    amount = 10**18
    holder = _cosmos_addr(stack, "signer2")
    voucher, voucher_before = await _mint_voucher(stack, holder, amount)

    # Return with a short timeout to a valid receiver; do NOT relay the recv.
    cosmos_send = send_v2_transfer(
        stack.dst_mantra,
        "signer2",
        source_client=stack.cosmos_client_id,
        receiver=ADDRS["signer1"],
        token_denom=voucher,
        amount=amount,
        timeout_timestamp=int(time.time()) + 8,
        fee_denom=stack.denom,
    )
    assert cosmos_send["code"] == 0, cosmos_send.get("raw_log")
    burned = ibc_voucher_balances(stack.dst_mantra, holder).get(voucher, 0)
    assert burned == voucher_before - amount, "send should burn the voucher"

    # Advance EVM chain past the timeout (non-receipt is proven at its latest block)
    await asyncio.sleep(12)
    target = await eth_w3.eth.block_number + 2
    while await eth_w3.eth.block_number < target:
        await asyncio.sleep(1)

    # Relay the cosmos MsgTimeout → ibcRouterV2 onTimeout refunds the voucher.
    timeout_tx = stack.relayer.relay_timeout_to_cosmos(
        src_chain=stack.eth_chain_id,
        dst_chain=stack.cosmos_chain_id,
        src_client_id=stack.eth_client_id,
        dst_client_id=stack.cosmos_client_id,
        timeout_tx_hash=bytes.fromhex(cosmos_send["txhash"]),
        cosmos_signer=cosmos_signer(
            stack.dst_mantra, stack.relayer_signer, denom=stack.denom
        ),
    )
    assert timeout_tx["code"] == 0, timeout_tx.get("raw_log")

    refunded = ibc_voucher_balances(stack.dst_mantra, holder).get(voucher, 0)
    assert refunded == voucher_before, "timeout should refund the voucher"


async def test_eureka_cosmos_native_to_eth_ibcerc20_mint(eth_to_cosmos_eureka_stack):
    """Cosmos-native asset → EVM: send ``atoken`` (a plain cosmos bank denom,
    foreign to the EVM source) over ibcRouterV2. On recv the EVM ICS20Transfer
    takes the MINT branch — deploys a fresh IBCERC20 for
    ``transfer/<eth_client>/atoken`` and mints ``amount`` to the receiver."""
    stack = eth_to_cosmos_eureka_stack
    eth_w3 = stack.eth_w3
    amount = 10**6
    native_denom = "atoken"  # held by the ``community`` account, not the gas denom
    eth_receiver = ADDRS["signer1"]
    full_denom = f"transfer/{stack.eth_client_id}/{native_denom}"

    # Cosmos sends a NATIVE denom (no EVM-origin prefix → the EVM mints a fresh
    # voucher rather than releasing escrow). Fees are still paid in the gas denom.
    cosmos_send = send_v2_transfer(
        stack.dst_mantra,
        "community",
        source_client=stack.cosmos_client_id,
        receiver=eth_receiver,
        token_denom=native_denom,
        amount=amount,
        timeout_timestamp=int(time.time()) + 600,
        fee_denom=stack.denom,
    )
    assert cosmos_send["code"] == 0, cosmos_send.get("raw_log")

    # Relay the recv to the EVM ICS26Router → ICS20Transfer mints the IBCERC20.
    recv = await stack.relayer.relay(
        stack.cosmos_ep, stack.relayer.src, bytes.fromhex(cosmos_send["txhash"])
    )
    assert recv["status"] == 1

    # A fresh IBCERC20 was deployed for the cosmos-native denom and minted to the
    # receiver (ibcERC20Contract reverts if the denom was never registered).
    token_addr = await stack.eth_transfer.fns.ibcERC20Contract(full_denom).call(
        eth_w3, to=stack.eth_transfer_addr
    )
    assert int(token_addr, 16) != 0, f"no IBCERC20 deployed for {full_denom}"
    bal = await ERC20.fns.balanceOf(eth_receiver).call(
        eth_w3, to=to_checksum_address(token_addr)
    )
    assert bal == amount, f"expected {amount} of minted {full_denom}, got {bal}"


# ---------------------------------------------------------------------------
# pydefi over the real relay (paired_eureka_stack + DeFiVM/Composer/MockV3Pool)
# ---------------------------------------------------------------------------


@dataclass
class PairedPydefiStack:
    paired: PairedEurekaStack
    pydefi: _PydefiPieces  # deployed on the src side


@pytest.fixture(scope="module")
async def paired_pydefi_stack(paired_eureka_stack) -> PairedPydefiStack:
    """``paired_eureka_stack`` + pydefi (DeFiVM, EurekaComposer, MockV3Pool)
    deployed on the src side, so pydefi flows run over the real attested relay."""
    src = paired_eureka_stack.src
    pydefi = await _deploy_pydefi(
        src.w3,
        src.deployer,
        test_erc20_addr=src.test_erc20_addr,
        transfer_addr=src.transfer_addr,
    )
    return PairedPydefiStack(paired=paired_eureka_stack, pydefi=pydefi)


def _ibc_denom_path(dst: _ChainSide, erc20_addr: ChecksumAddress) -> str:
    """The dst-side IBCERC20 denom for a token bridged from src (origin EVM)."""
    return f"transfer/{dst.client_id}/0x" + bytes(HexBytes(erc20_addr)).hex().lower()


async def _ibc_erc20_balance(dst: _ChainSide, denom_path: str, holder: str) -> int:
    """``holder``'s balance of the dst IBCERC20 for ``denom_path``; 0 if the token
    hasn't been minted yet (``ibcERC20Contract`` reverts before first mint)."""
    try:
        token = await dst.transfer.fns.ibcERC20Contract(denom_path).call(
            dst.w3, to=dst.transfer_addr
        )
    except Exception:
        return 0
    return await ERC20.fns.balanceOf(HexBytes(holder)).call(
        dst.w3, to=to_checksum_address(token)
    )


def _followup_program() -> bytes:
    """Trivial follow-up Program: re-emit the success flag the composer puts in
    slot 0 (1 on ack-success, 0 on ack-error / timeout)."""
    prog = Program()
    prog.return_word(prog.builder.tload(0))
    return prog.build()


def _bridge_program(
    *, transfer_addr, denom, amount: int, receiver: str, source_client: str
) -> bytes:
    """A DeFiVM Program that approves + ICS20 sendTransfers ``denom`` to ``receiver``"""
    prog = Program()
    ok = approve_then_send_transfer(
        prog,
        transfer_addr=HexBytes(transfer_addr),
        denom=HexBytes(denom),
        amount=amount,
        receiver=receiver,
        source_client=source_client,
        timeout_seconds=600,
    )
    prog.assert_(ok, "sendTransfer failed")
    prog.builder.stop()
    return prog.build()


async def _compose(
    w3,
    deployer,
    *,
    composer_addr,
    test_erc20_addr,
    router_addr,
    source_client: str,
    receiver: str,
    amount: int,
    program_bytes: bytes,
    timeout_secs: int = 600,
):
    """Approve + EurekaComposer.sendTransferAndCompose, return (receipt, sequence)"""
    await ERC20.fns.approve(composer_addr, amount).transact(
        w3, deployer, to=test_erc20_addr
    )
    calldata = encode_send_and_compose_calldata(
        denom=HexBytes(test_erc20_addr),
        amount=amount,
        receiver=receiver,
        source_client=source_client,
        timeout_timestamp=int(time.time()) + timeout_secs,
        program=program_bytes,
    )
    receipt = await send_transaction(
        w3, deployer, to=composer_addr, data=calldata, gas=900_000
    )
    assert receipt["status"] == 1
    events = await observe_send_packets(
        w3,
        Contract(get_contract("ICS26Router")["abi"]),
        router_addr,
        from_block=receipt["blockNumber"],
        to_block=receipt["blockNumber"],
    )
    assert len(events) == 1, "composer didn't reach the router"
    return receipt, int(events[0]["packet"]["sequence"])


async def _assert_composer_ran(
    composer,
    composer_addr,
    w3,
    source_client: str,
    sequence: int,
    receipt,
    *,
    event: str,
    success: bool | None = None,
):
    """The composer cleared the (sourceClient, sequence) slot and emitted event"""
    cleared = await composer.fns.programs(source_client, sequence).call(
        w3, to=composer_addr
    )
    assert bytes(cleared) == b"", "program not cleared"
    logs = await getattr(composer.events, event).get_logs(
        w3,
        address=composer_addr,
        from_block=receipt["blockNumber"],
        to_block=receipt["blockNumber"],
    )
    assert len(logs) == 1, f"no {event}"
    assert int(logs[0]["args"]["sequence"]) == sequence
    if success is not None:
        assert logs[0]["args"]["success"] is success


async def test_eureka_defivm_bridge_via_real_relay(paired_pydefi_stack):
    """A DeFiVM Program (approve + sendTransfer) on src, relayed over the real
    attested relayer, mints the IBCERC20 voucher to the receiver on dst."""
    src, dst = paired_pydefi_stack.paired.src, paired_pydefi_stack.paired.dst
    relayer = paired_pydefi_stack.paired.binary_relayer
    p = paired_pydefi_stack.pydefi
    amount = 10**18
    receiver = HexBytes(ADDRS["signer1"]).to_0x_hex()
    denom_path = _ibc_denom_path(dst, src.test_erc20_addr)
    before = await _ibc_erc20_balance(dst, denom_path, receiver)

    program = _bridge_program(
        transfer_addr=src.transfer_addr,
        denom=src.test_erc20_addr,
        amount=amount,
        receiver=receiver,
        source_client=src.client_id,
    )
    send_receipt = await p.defivm.fns.execute(program).transact(
        src.w3, src.deployer, to=p.defivm_addr
    )
    assert send_receipt["status"] == 1

    # Real relay src→dst (recv+mint), then the ack leg back to src (finalize).
    recv_receipt = await relayer.relay(
        relayer.src, relayer.dst, bytes(send_receipt["transactionHash"])
    )
    after = await _ibc_erc20_balance(dst, denom_path, receiver)
    assert after - before == amount, "DeFiVM-initiated bridge didn't mint on dst"
    ack_receipt = await relayer.relay(
        relayer.dst, relayer.src, bytes(recv_receipt["transactionHash"])
    )
    assert ack_receipt["status"] == 1


async def test_eureka_swap_then_bridge_via_real_relay(paired_pydefi_stack):
    """A DeFiVM RouteDAG (swap WETH→USDC on the MockV3Pool, then bridge), relayed
    over the real relayer, mints the swapped USDC as an IBCERC20 on dst."""
    src, dst = paired_pydefi_stack.paired.src, paired_pydefi_stack.paired.dst
    relayer = paired_pydefi_stack.paired.binary_relayer
    p = paired_pydefi_stack.pydefi
    amount_in = 10**18
    receiver = HexBytes(ADDRS["signer2"]).to_0x_hex()
    denom_path = _ibc_denom_path(dst, src.test_erc20_addr)
    before = await _ibc_erc20_balance(dst, denom_path, receiver)

    dag = (
        RouteDAG()
        .from_token(p.weth_token)
        .swap(p.usdc_token, p.v3_pool)
        .bridge(
            p.usdc_token_dst,
            transfer_addr=HexBytes(src.transfer_addr),
            source_client=src.client_id,
            receiver=receiver,
            timeout_seconds=600,
        )
    )
    prog = build_execution_program_for_dag(
        dag, amount_in=amount_in, vm_address=p.defivm_addr, recipient=p.defivm_addr
    )
    send_receipt = await p.defivm.fns.execute(prog.build()).transact(
        src.w3, src.deployer, to=p.defivm_addr
    )
    assert send_receipt["status"] == 1

    await relayer.relay(
        relayer.src, relayer.dst, bytes(send_receipt["transactionHash"])
    )

    after = await _ibc_erc20_balance(dst, denom_path, receiver)
    assert after - before == amount_in, "swap-then-bridge didn't mint on dst (1:1 pool)"


async def test_eureka_composer_ack_callback_via_real_relay(paired_pydefi_stack):
    """A composed transfer's recv relayed to dst (mint), then the REAL ack back to
    src, fires the composer's onAckPacket — the Program runs and the slot clears."""
    src = paired_pydefi_stack.paired.src
    relayer = paired_pydefi_stack.paired.binary_relayer
    p = paired_pydefi_stack.pydefi
    amount = 10**18
    program_bytes = _followup_program()

    send_receipt, sequence = await _compose(
        src.w3,
        src.deployer,
        composer_addr=p.composer_addr,
        test_erc20_addr=src.test_erc20_addr,
        router_addr=src.router_addr,
        source_client=src.client_id,
        receiver=HexBytes(ADDRS["signer1"]).to_0x_hex(),
        amount=amount,
        program_bytes=program_bytes,
    )
    stored = await p.composer.fns.programs(src.client_id, sequence).call(
        src.w3, to=p.composer_addr
    )
    assert bytes(stored) == bytes(program_bytes), "program not registered"

    # Real relay: src→dst (recv+mint), then dst→src (the REAL ack).
    recv_receipt = await relayer.relay(
        relayer.src, relayer.dst, bytes(send_receipt["transactionHash"])
    )
    ack_receipt = await relayer.relay(
        relayer.dst, relayer.src, bytes(recv_receipt["transactionHash"])
    )
    await _assert_composer_ran(
        p.composer,
        p.composer_addr,
        src.w3,
        src.client_id,
        sequence,
        ack_receipt,
        event="AckExecuted",
        success=True,
    )


async def test_eureka_composer_timeout_callback_via_real_relay(paired_pydefi_stack):
    """A composed transfer with a short timeout, never relayed; a REAL timeout back
    to src fires onTimeoutPacket → refund the composer, run the Program, clear slot."""
    src, dst = paired_pydefi_stack.paired.src, paired_pydefi_stack.paired.dst
    relayer = paired_pydefi_stack.paired.binary_relayer
    p = paired_pydefi_stack.pydefi
    amount = 10**18

    composer_before = await ERC20.fns.balanceOf(p.composer_addr).call(
        src.w3, to=src.test_erc20_addr
    )
    send_receipt, sequence = await _compose(
        src.w3,
        src.deployer,
        composer_addr=p.composer_addr,
        test_erc20_addr=src.test_erc20_addr,
        router_addr=src.router_addr,
        source_client=src.client_id,
        receiver=HexBytes(ADDRS["signer1"]).to_0x_hex(),
        amount=amount,
        program_bytes=_followup_program(),
        timeout_secs=8,
    )

    # Do NOT relay the recv. Wait past the timeout and advance dst so its latest
    # block (where non-receipt is proven) is beyond the packet timeout.
    await asyncio.sleep(12)
    target = await dst.w3.eth.block_number + 2
    while await dst.w3.eth.block_number < target:
        await asyncio.sleep(1)

    # Real timeout relayed to src: onTimeoutPacket refunds + composer runs Program.
    timeout_receipt = await relayer.relay_timeout(
        src_chain=relayer.dst.chain_id,
        dst_chain=relayer.src.chain_id,
        src_client_id=dst.client_id,
        dst_client_id=src.client_id,
        timeout_tx_hash=bytes(send_receipt["transactionHash"]),
        to_side=relayer.src,
    )
    assert timeout_receipt["status"] == 1

    composer_after = await ERC20.fns.balanceOf(p.composer_addr).call(
        src.w3, to=src.test_erc20_addr
    )
    assert composer_after - composer_before == amount, "timeout didn't refund composer"
    await _assert_composer_ran(
        p.composer,
        p.composer_addr,
        src.w3,
        src.client_id,
        sequence,
        timeout_receipt,
        event="TimeoutExecuted",
    )


@dataclass
class EthToCosmosPydefiStack:
    stack: EthToCosmosEurekaStack
    pydefi: _PydefiPieces  # deployed on the EVM source


@pytest.fixture(scope="module")
async def eth_to_cosmos_pydefi_stack(
    eth_to_cosmos_eureka_stack,
) -> EthToCosmosPydefiStack:
    """``eth_to_cosmos_eureka_stack`` + pydefi (DeFiVM/EurekaComposer/MockV3Pool)
    on the EVM source, so pydefi can bridge to a cosmos dest over ibcRouterV2."""
    stack = eth_to_cosmos_eureka_stack
    pydefi = await _deploy_pydefi(
        stack.eth_w3,
        Account.from_key(KEYS["community"]),
        test_erc20_addr=stack.eth_test_erc20_addr,
        transfer_addr=stack.eth_transfer_addr,
    )
    return EthToCosmosPydefiStack(stack=stack, pydefi=pydefi)


async def test_eureka_defivm_bridge_to_cosmos_via_router_v2(eth_to_cosmos_pydefi_stack):
    """A DeFiVM Program sendTransfers to a cosmos bech32 receiver, relayed into evmd
    over ibcRouterV2, minting the voucher — bridging to cosmos is the same as any
    EVM dest, just a bech32 receiver + the EVM→cosmos client."""
    stack = eth_to_cosmos_pydefi_stack.stack
    p = eth_to_cosmos_pydefi_stack.pydefi
    amount = 10**18
    receiver = _cosmos_addr(stack, "signer2")
    before = ibc_voucher_balances(stack.dst_mantra, receiver)

    program = _bridge_program(
        transfer_addr=stack.eth_transfer_addr,
        denom=stack.eth_test_erc20_addr,
        amount=amount,
        receiver=receiver,
        source_client=stack.eth_client_id,
    )
    send_receipt = await p.defivm.fns.execute(program).transact(
        stack.eth_w3, Account.from_key(KEYS["community"]), to=p.defivm_addr
    )
    assert send_receipt["status"] == 1

    # Real relay into evmd: ibcRouterV2 → transfer app mints the voucher.
    recv_tx = _relay_recv_ack(stack, bytes(send_receipt["transactionHash"]))
    assert recv_tx["code"] == 0, recv_tx.get("raw_log")

    after = ibc_voucher_balances(stack.dst_mantra, receiver)
    assert any(
        after[d] - before.get(d, 0) == amount for d in after
    ), "DeFiVM-initiated bridge didn't mint the cosmos voucher"


async def test_eureka_composer_error_ack_callback_via_real_relay(paired_pydefi_stack):
    """Failure branch: receiver=0x0 makes the dst recv fail (error ack); relayed
    back, it refunds the composer and fires onAckPacket(success=False), Program
    still runs."""
    src = paired_pydefi_stack.paired.src
    relayer = paired_pydefi_stack.paired.binary_relayer
    p = paired_pydefi_stack.pydefi
    amount = 10**18

    composer_before = await ERC20.fns.balanceOf(p.composer_addr).call(
        src.w3, to=src.test_erc20_addr
    )
    # receiver=0x0 → the dst escrow.send reverts → ICS26Router writes an error ack.
    send_receipt, sequence = await _compose(
        src.w3,
        src.deployer,
        composer_addr=p.composer_addr,
        test_erc20_addr=src.test_erc20_addr,
        router_addr=src.router_addr,
        source_client=src.client_id,
        receiver="0x" + "0" * 40,
        amount=amount,
        program_bytes=_followup_program(),
    )
    recv_receipt = await relayer.relay(
        relayer.src, relayer.dst, bytes(send_receipt["transactionHash"])
    )
    ack_receipt = await relayer.relay(
        relayer.dst, relayer.src, bytes(recv_receipt["transactionHash"])
    )

    # Error ack refunded the composer; slot cleared and onAckPacket ran success=False.
    composer_after = await ERC20.fns.balanceOf(p.composer_addr).call(
        src.w3, to=src.test_erc20_addr
    )
    assert (
        composer_after - composer_before == amount
    ), "error ack should refund composer"
    await _assert_composer_ran(
        p.composer,
        p.composer_addr,
        src.w3,
        src.client_id,
        sequence,
        ack_receipt,
        event="AckExecuted",
        success=False,
    )


async def test_eureka_composer_ack_callback_to_cosmos(eth_to_cosmos_pydefi_stack):
    """A composed transfer to a cosmos receiver: recv into evmd (voucher mint), then
    the real ack back to the EVM source fires onAckPacket (Program runs, slot clears)"""
    stack = eth_to_cosmos_pydefi_stack.stack
    p = eth_to_cosmos_pydefi_stack.pydefi
    amount = 10**18

    send_receipt, sequence = await _compose(
        stack.eth_w3,
        Account.from_key(KEYS["community"]),
        composer_addr=p.composer_addr,
        test_erc20_addr=stack.eth_test_erc20_addr,
        router_addr=stack.eth_router_addr,
        source_client=stack.eth_client_id,
        receiver=_cosmos_addr(stack, "signer2"),
        amount=amount,
        program_bytes=_followup_program(),
    )

    # Relay recv into evmd (ibcRouterV2 mints the voucher), then the real ack back.
    recv_tx = _relay_recv_ack(stack, bytes(send_receipt["transactionHash"]))
    assert recv_tx["code"] == 0, recv_tx.get("raw_log")
    ack_receipt = await stack.relayer.relay(
        stack.cosmos_ep, stack.relayer.src, bytes.fromhex(recv_tx["txhash"])
    )
    assert ack_receipt["status"] == 1
    await _assert_composer_ran(
        p.composer,
        p.composer_addr,
        stack.eth_w3,
        stack.eth_client_id,
        sequence,
        ack_receipt,
        event="AckExecuted",
        success=True,
    )

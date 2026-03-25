import pytest
from web3 import AsyncWeb3

from .ibc_utils import prepare_network
from .utils import (
    ACCOUNTS,
    build_and_deploy_contract_async,
)

pytestmark = pytest.mark.asyncio

OP_PUSH_U256 = 0x01
OP_PUSH_ADDR = 0x02
OP_PUSH_BYTES = 0x03
OP_POP = 0x06
OP_ASSERT_GE = 0x23
OP_CALL = 0x30
OP_SELF_BAL = 0x32
OP_DELTA_START = 0x33
OP_DELTA_LOAD = 0x34


def push_u256(n: int) -> bytes:
    return bytes([OP_PUSH_U256]) + n.to_bytes(32, "big")


def push_addr(a: str) -> bytes:
    raw = bytes.fromhex(a.removeprefix("0x"))
    if len(raw) != 20:
        raise ValueError(f"bad address length: {a!r}")
    return bytes([OP_PUSH_ADDR]) + raw


def push_bytes(data: bytes) -> bytes:
    if len(data) > 0xFFFF:
        raise ValueError("push_bytes payload too large")
    return bytes([OP_PUSH_BYTES]) + len(data).to_bytes(2, "big") + data


def pop() -> bytes:
    return bytes([OP_POP])


def assert_ge(msg: str = "") -> bytes:
    raw = msg.encode()
    if len(raw) > 255:
        raise ValueError("assert_ge message too long")
    return bytes([OP_ASSERT_GE, len(raw)]) + raw


def self_bal() -> bytes:
    return bytes([OP_SELF_BAL])


def call(require_success: bool = True) -> bytes:
    flags = 0x01 if require_success else 0x00
    return bytes([OP_CALL, flags])


def delta_start() -> bytes:
    return bytes([OP_DELTA_START])


def delta_load() -> bytes:
    return bytes([OP_DELTA_LOAD])


@pytest.fixture(scope="module")
def ibc(request, tmp_path_factory):
    "prepare-network"
    name = "ibc"
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp(name)
    yield from prepare_network(path, name, chain)


async def test_flow(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    deployer = ACCOUNTS["community"]

    vm = await build_and_deploy_contract_async(w3, "DeFiVM")

    # Snapshot and load ETH delta for same account without transfers (expect zero delta)
    program = (
        push_addr(deployer.address)
        + push_addr("0x0000000000000000000000000000000000000000")
        + delta_start()
        + push_addr(deployer.address)
        + push_addr("0x0000000000000000000000000000000000000000")
        + delta_load()
        + push_u256(0)
        + pop()
        + pop()
    )
    tx_hash = await vm.functions.execute(program).transact({"from": deployer.address})
    receipt = await w3.eth.get_transaction_receipt(tx_hash)
    assert receipt["status"] == 1

    value_in = 10**15
    vm_before = await w3.eth.get_balance(vm.address)
    sender_before = await w3.eth.get_balance(deployer.address)

    # Check VM onchain balance during execution and then verify final balances offchain
    program = push_u256(value_in) + self_bal() + assert_ge("vm balance too low")
    tx_hash = await vm.functions.execute(program).transact(
        {"from": deployer.address, "value": value_in}
    )
    receipt = await w3.eth.get_transaction_receipt(tx_hash)
    assert receipt["status"] == 1

    vm_after = await w3.eth.get_balance(vm.address)
    sender_after = await w3.eth.get_balance(deployer.address)
    gas_cost = receipt["effectiveGasPrice"] * receipt["gasUsed"]

    assert vm_after == vm_before + value_in
    assert sender_before - sender_after == value_in + gas_cost


async def test_ibc_cb(ibc):
    w3: AsyncWeb3 = ibc.ibc1.async_w3
    deployer = ACCOUNTS["community"]

    vm = await build_and_deploy_contract_async(w3, "DeFiVM")
    cb = await build_and_deploy_contract_async(w3, "CounterWithCallbacks")

    # DeFiVM only allows CALLs to whitelisted adapters.
    set_adapter_tx = await vm.functions.setAdapter(cb.address, True).transact(
        {"from": deployer.address}
    )
    set_adapter_receipt = await w3.eth.get_transaction_receipt(set_adapter_tx)
    assert set_adapter_receipt["status"] == 1

    channel_id = "channel-0"
    port_id = "transfer"
    sequence = 7
    payload = b"ibc_payload\x00hello\xff"
    acknowledgement = b'{"result":"ok","payload":true}'

    tx = await cb.functions.onPacketAcknowledgement(
        channel_id, port_id, sequence, payload, acknowledgement
    ).build_transaction({"from": deployer.address, "gas": 300_000})
    calldata = bytes.fromhex(tx["data"][2:])

    # Stack order for CALL is (top -> bottom): gasLimit, to, value, calldataBufIdx
    program = (
        push_bytes(calldata)
        + push_u256(0)
        + push_addr(cb.address)
        + push_u256(300_000)
        + call(True)
        + pop()
    )

    exec_tx = await vm.functions.execute(program).transact({"from": deployer.address})
    exec_receipt = await w3.eth.get_transaction_receipt(exec_tx)
    assert exec_receipt["status"] == 1

    assert await cb.functions.counter().call() == 1

    callback_logs = cb.events.PacketAcknowledged().process_receipt(exec_receipt)
    assert len(callback_logs) == 1
    event_args = callback_logs[0]["args"]
    assert event_args["channelId"] == w3.keccak(text=channel_id)
    assert event_args["portId"] == w3.keccak(text=port_id)
    assert event_args["sequence"] == sequence
    assert event_args["data"] == payload
    assert event_args["acknowledgement"] == acknowledgement

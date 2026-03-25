import pytest
from web3 import AsyncWeb3

from .utils import (
    ACCOUNTS,
    build_and_deploy_contract_async,
)

pytestmark = pytest.mark.asyncio

OP_PUSH_U256 = 0x01
OP_PUSH_ADDR = 0x02
OP_POP = 0x06
OP_ASSERT_GE = 0x23
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


def pop() -> bytes:
    return bytes([OP_POP])


def assert_ge(msg: str = "") -> bytes:
    raw = msg.encode()
    if len(raw) > 255:
        raise ValueError("assert_ge message too long")
    return bytes([OP_ASSERT_GE, len(raw)]) + raw


def self_bal() -> bytes:
    return bytes([OP_SELF_BAL])


def delta_start() -> bytes:
    return bytes([OP_DELTA_START])


def delta_load() -> bytes:
    return bytes([OP_DELTA_LOAD])


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

import itertools
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from eth_contract.create2 import CREATE2_FACTORY, create2_address
from eth_contract.deploy_utils import (
    ensure_create2_deployed,
    ensure_deployed_by_create2,
    ensure_multicall3_deployed,
)
from eth_contract.erc20 import ERC20
from eth_contract.multicall3 import MULTICALL3, Call3
from eth_contract.utils import get_initcode
from pystarport.utils import w3_wait_for_new_blocks

from .expected_constants import (
    EXPECTED_CALLTRACERS,
    EXPECTED_CONTRACT_CREATE_TRACER,
    EXPECTED_STRUCT_TRACER,
)
from .utils import (
    ACCOUNTS,
    ADDRS,
    Contract,
    MockERC20_ARTIFACT,
    build_contract,
    create_contract_transaction,
    derive_new_account,
    derive_random_account,
    fund_acc,
    send_transaction,
    send_transaction_async,
)

METHOD = "debug_traceTransaction"
CALL_TRACER = {"tracer": "callTracer"}
RETURN_42_RUNTIME = bytes.fromhex("602a60005260206000f3")
DESTRUCT_RUNTIME = bytes.fromhex("6000ff")  # PUSH1 0 SELFDESTRUCT


def test_out_of_gas_error(mantra):
    w3 = mantra.w3
    acc = derive_random_account()
    # fund new sender to deploy contract with same address
    fund_acc(w3, acc)
    msg = Contract("TestMessageCall", acc.key)
    msg.deploy(w3)
    tx = msg.contract.functions.test(1).build_transaction({"gas": 21510})
    tx_hash = send_transaction(w3, tx)["transactionHash"].to_0x_hex()
    resp = w3.provider.make_request(METHOD, [tx_hash, CALL_TRACER])
    assert "out of gas" in resp["result"]["error"], resp


def test_storage_out_of_gas_error(mantra):
    w3 = mantra.w3
    acc = derive_new_account(8)
    # fund new sender to deploy contract with same address
    fund_acc(w3, acc)
    tx = create_contract_transaction(w3, "TestMessageCall", key=acc.key)
    tx["gas"] = 210000
    tx_hash = send_transaction(w3, tx, key=acc.key)["transactionHash"].to_0x_hex()
    resp = w3.provider.make_request(METHOD, [tx_hash, CALL_TRACER])
    msg = "contract creation code storage out of gas"
    assert msg in resp["result"]["error"], resp


def test_trace_transactions_tracers(mantra):
    w3 = mantra.w3
    call = w3.provider.make_request
    acc = derive_new_account(7)
    fund_acc(w3, acc)
    tx = {"to": ADDRS["signer1"], "value": 100, "gasPrice": hex(88500000000)}
    tx_hash = send_transaction(w3, tx)["transactionHash"].to_0x_hex()
    assert call(METHOD, [tx_hash])["result"] == EXPECTED_STRUCT_TRACER
    assert call(METHOD, [tx_hash, CALL_TRACER])["result"] == EXPECTED_CALLTRACERS
    top_call = CALL_TRACER | {"tracerConfig": {"onlyTopCall": True}}
    assert call(METHOD, [tx_hash, top_call])["result"] == EXPECTED_CALLTRACERS

    res = build_contract("TestERC20A")
    contract = w3.eth.contract(abi=res["abi"], bytecode=res["bytecode"])
    tx = contract.constructor().build_transaction({"from": acc.address})
    tx_hash = send_transaction(w3, tx, key=acc.key)["transactionHash"].to_0x_hex()
    w3_wait_for_new_blocks(w3, 1)
    tx_res = call(METHOD, [tx_hash, CALL_TRACER])
    assert tx_res["result"] == EXPECTED_CONTRACT_CREATE_TRACER


def test_trace_tx(mantra):
    w3 = mantra.w3
    tracers = [
        [],
        [CALL_TRACER],
        [CALL_TRACER | {"tracerConfig": {"onlyTopCall": True}}],
        [CALL_TRACER | {"tracerConfig": {"withLog": True}}],
        [CALL_TRACER | {"tracerConfig": {"diffMode": True}}],
    ]
    acc = derive_random_account()
    # fund new sender to deploy contract with same address
    fund_acc(w3, acc)
    msg = Contract("TestMessageCall", acc.key)
    msg.deploy(w3)
    tx = msg.contract.functions.test(1).build_transaction()
    tx_hash = send_transaction(w3, tx)["transactionHash"].to_0x_hex()
    # trace the same tx under every tracer at once
    with ThreadPoolExecutor(len(tracers)) as executor:
        params = [[tx_hash] + cfg for cfg in tracers]
        for resp in executor.map(
            w3.provider.make_request, itertools.repeat(METHOD), params
        ):
            assert "result" in resp, resp


def _frames(trace: dict) -> list[dict]:
    """A callTracer trace's frames, root first."""
    return [
        trace,
        *(frame for call in trace.get("calls", []) for frame in _frames(call)),
    ]


async def _trace(w3, receipt, *config) -> dict:
    """``debug_traceTransaction`` of ``receipt``'s tx."""
    tx_hash = receipt["transactionHash"].to_0x_hex()
    return (await w3.provider.make_request(METHOD, [tx_hash, *config]))["result"]


async def _deploy(w3, account, runtime: bytes) -> str:
    """Address of a contract running ``runtime`` (under 256 bytes), deployed once."""
    size = bytes([len(runtime)])
    # Copy the runtime out past these 12 bytes and return it.
    initcode = b"\x60" + size + b"\x60\x0c\x60\x00\x39\x60" + size + b"\x60\x00\xf3"
    await ensure_create2_deployed(w3, account)
    return await ensure_deployed_by_create2(w3, account, initcode + runtime)


@pytest.mark.asyncio
async def test_call_tracer_shows_every_call_of_a_batch(mantra):
    """Each call a Multicall3 batch makes is a frame, the CREATE2 one included."""
    w3 = mantra.async_w3
    account = ACCOUNTS["community"]
    await ensure_create2_deployed(w3, account)
    await ensure_multicall3_deployed(w3, account)
    initcode = get_initcode(MockERC20_ARTIFACT, "TEST", "TEST", 18)
    salt = os.urandom(32)  # a fresh address each run, or the CREATE2 call reverts
    token = create2_address(initcode, salt)
    calls = [
        Call3(CREATE2_FACTORY, data=salt + initcode),
        Call3(token, data=ERC20.fns.balanceOf(account.address).data),
    ]
    receipt = await MULTICALL3.fns.aggregate3(calls).transact(w3, account)
    trace = await _trace(w3, receipt, CALL_TRACER)
    frames = [(frame["type"], frame["to"].lower()) for frame in _frames(trace)]
    assert ("CREATE2", token.lower()) in frames, frames
    assert ("CALL", token.lower()) in frames, frames


@pytest.mark.asyncio
async def test_struct_logs_of_a_batch_follow_each_call(mantra):
    """A batch's calls log the opcodes they log when sent alone, one level deeper."""
    w3 = mantra.async_w3
    account = ACCOUNTS["community"]
    await ensure_multicall3_deployed(w3, account)
    target = await _deploy(w3, account, RETURN_42_RUNTIME)
    receipts = [
        await send_transaction_async(w3, account, to=target),
        await MULTICALL3.fns.aggregate3([Call3(target)] * 2).transact(w3, account),
    ]
    alone, batch = [(await _trace(w3, r))["structLogs"] for r in receipts]
    call = [(log["op"], log["depth"] + 1) for log in alone]
    assert call, "a single call's struct logs"
    assert [(log["op"], log["depth"]) for log in batch if log["depth"] > 1] == call * 2


@pytest.mark.asyncio
async def test_a_self_destruct_in_a_batch_is_traced_once(mantra):
    """A batch whose last call self-destructs shows that self-destruct alone."""
    w3 = mantra.async_w3
    account = ACCOUNTS["community"]
    await ensure_multicall3_deployed(w3, account)
    ok = await _deploy(w3, account, RETURN_42_RUNTIME)
    doomed = await _deploy(w3, account, DESTRUCT_RUNTIME)
    calls = [Call3(ok), Call3(doomed)]
    receipt = await MULTICALL3.fns.aggregate3(calls).transact(w3, account)
    trace = await _trace(w3, receipt, CALL_TRACER)
    destroyed = [
        f["from"].lower() for f in _frames(trace) if f["type"] == "SELFDESTRUCT"
    ]
    assert destroyed == [doomed.lower()], trace

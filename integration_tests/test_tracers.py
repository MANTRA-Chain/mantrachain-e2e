import itertools
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from eth_contract.create2 import CREATE2_FACTORY, create2_address
from eth_contract.deploy_utils import (
    ensure_create2_deployed,
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
)

METHOD = "debug_traceTransaction"
CALL_TRACER = {"tracer": "callTracer"}


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


def _frames(trace: dict) -> list[tuple[str, str | None]]:
    """A callTracer trace's frames as ``(type, to)``, root first."""
    frames = [(trace["type"], trace.get("to") and trace["to"].lower())]
    for call in trace.get("calls", []):
        frames += _frames(call)
    return frames


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
    tx_hash = receipt["transactionHash"].to_0x_hex()
    trace = (await w3.provider.make_request(METHOD, [tx_hash, CALL_TRACER]))["result"]
    frames = _frames(trace)
    assert ("CREATE2", token.lower()) in frames, frames
    assert ("CALL", token.lower()) in frames, frames

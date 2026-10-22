import itertools
from concurrent.futures import ThreadPoolExecutor

from pystarport.utils import w3_wait_for_new_blocks

from .expected_constants import (
    EXPECTED_CALLTRACERS,
    EXPECTED_CONTRACT_CREATE_TRACER,
    EXPECTED_STRUCT_TRACER,
)
from .utils import (
    ADDRS,
    Contract,
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

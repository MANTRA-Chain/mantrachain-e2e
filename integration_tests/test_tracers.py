import itertools
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from .expected_constants import (
    EXPECTED_CALLTRACERS,
    EXPECTED_CONTRACT_CREATE_TRACER,
    EXPECTED_STRUCT_TRACER,
)
from .utils import (
    ADDRS,
    CONTRACTS,
    Contract,
    create_contract_transaction,
    deploy_contract_with_receipt,
    derive_new_account,
    derive_random_account,
    fund_acc,
    send_transaction,
    w3_wait_for_new_blocks,
)


def test_out_of_gas_error(mantra):
    method = "debug_traceTransaction"
    tracer = {"tracer": "callTracer"}
    iterations = 1
    acc = derive_random_account()

    def process(w3):
        # fund new sender to deploy contract with same address
        fund_acc(w3, acc)
        msg = Contract("TestMessageCall", acc.key)
        msg.deploy(mantra.w3)
        contract = msg.contract
        tx = contract.functions.test(iterations).build_transaction({"gas": 21510})
        tx_hash = send_transaction(w3, tx)["transactionHash"].hex()
        tx_hash = f"0x{tx_hash}"
        res = []
        call = w3.provider.make_request
        resp = call(method, [tx_hash, tracer])
        assert "out of gas" in resp["result"]["error"], resp
        res = [json.dumps(resp["result"], sort_keys=True)]
        return res

    providers = [mantra.w3]
    with ThreadPoolExecutor(len(providers)) as exec:
        tasks = [exec.submit(process, w3) for w3 in providers]
        res = [future.result() for future in as_completed(tasks)]
        assert len(res) == len(providers)
        assert res[0] == res[-1], res


def test_storage_out_of_gas_error(mantra):
    method = "debug_traceTransaction"
    tracer = {"tracer": "callTracer"}
    acc = derive_new_account(8)

    def process(w3):
        # fund new sender to deploy contract with same address
        fund_acc(w3, acc)
        tx = create_contract_transaction(w3, "TestMessageCall", key=acc.key)
        tx["gas"] = 210000
        tx_hash = send_transaction(w3, tx, key=acc.key)["transactionHash"].hex()
        tx_hash = f"0x{tx_hash}"
        res = []
        call = w3.provider.make_request
        resp = call(method, [tx_hash, tracer])
        msg = "contract creation code storage out of gas"
        assert msg in resp["result"]["error"], resp
        res = [json.dumps(resp["result"], sort_keys=True)]
        return res

    providers = [mantra.w3]
    with ThreadPoolExecutor(len(providers)) as exec:
        tasks = [exec.submit(process, w3) for w3 in providers]
        res = [future.result() for future in as_completed(tasks)]
        assert len(res) == len(providers)
        assert res[0] == res[-1], res


def test_trace_transactions_tracers(mantra):
    method = "debug_traceTransaction"
    tracer = {"tracer": "callTracer"}
    price = hex(88500000000)
    acc = derive_new_account(7)

    def process(w3):
        fund_acc(w3, acc)
        call = w3.provider.make_request
        tx = {"to": ADDRS["community"], "value": 100, "gasPrice": price}
        tx_hash = send_transaction(w3, tx)["transactionHash"].hex()
        tx_hash = f"0x{tx_hash}"
        tx_res = call(method, [tx_hash])
        assert tx_res["result"] == EXPECTED_STRUCT_TRACER, ""
        tx_res = call(method, [tx_hash, tracer])
        assert tx_res["result"] == EXPECTED_CALLTRACERS, ""
        tx_res = call(
            method,
            [tx_hash, tracer | {"tracerConfig": {"onlyTopCall": True}}],
        )
        assert tx_res["result"] == EXPECTED_CALLTRACERS, ""
        _, tx = deploy_contract_with_receipt(w3, CONTRACTS["TestERC20A"], key=acc.key)
        tx_hash = tx["transactionHash"].hex()
        tx_hash = f"0x{tx_hash}"
        w3_wait_for_new_blocks(w3, 1)
        tx_res = call(method, [tx_hash, tracer])
        return json.dumps(tx_res["result"], sort_keys=True)

    providers = [mantra.w3]
    with ThreadPoolExecutor(len(providers)) as exec:
        tasks = [exec.submit(process, w3) for w3 in providers]
        res = [future.result() for future in as_completed(tasks)]
        assert len(res) == len(providers)
        assert res[0] == res[-1] == EXPECTED_CONTRACT_CREATE_TRACER, res


def test_trace_tx(mantra):
    method = "debug_traceTransaction"
    tracer = {"tracer": "callTracer"}
    tracers = [
        [],
        [tracer],
        [tracer | {"tracerConfig": {"onlyTopCall": True}}],
        [tracer | {"tracerConfig": {"withLog": True}}],
        [tracer | {"tracerConfig": {"diffMode": True}}],
    ]
    iterations = 1
    acc = derive_random_account()

    def process(w3):
        # fund new sender to deploy contract with same address
        fund_acc(w3, acc)
        msg = Contract("TestMessageCall", acc.key)
        msg.deploy(mantra.w3)
        contract = msg.contract
        tx = contract.functions.test(iterations).build_transaction()
        tx_hash = send_transaction(w3, tx)["transactionHash"].hex()
        tx_hash = f"0x{tx_hash}"
        res = []
        call = w3.provider.make_request
        with ThreadPoolExecutor(len(tracers)) as exec:
            params = [([tx_hash] + cfg) for cfg in tracers]
            exec_map = exec.map(call, itertools.repeat(method), params)
            res = [json.dumps(resp["result"], sort_keys=True) for resp in exec_map]
        return res

    providers = [mantra.w3]
    with ThreadPoolExecutor(len(providers)) as exec:
        tasks = [exec.submit(process, w3) for w3 in providers]
        res = [future.result() for future in as_completed(tasks)]
        assert len(res) == len(providers)
        assert res[0] == res[-1], res

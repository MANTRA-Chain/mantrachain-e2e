import itertools
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from .expected_constants import (
    EXPECTED_CALLTRACERS,
    EXPECTED_CONTRACT_CREATE_TRACER,
    EXPECTED_STRUCT_TRACER,
)
from .utils import (
    ADDRS,
    CONTRACTS,
    create_contract_transaction,
    deploy_contract,
    derive_new_account,
    derive_random_account,
    fund_acc,
    send_raw_transactions,
    send_transaction,
    sign_transaction,
    w3_wait_for_new_blocks,
    wait_for_fn,
)


def test_out_of_gas_error(mantra):
    method = "debug_traceTransaction"
    tracer = {"tracer": "callTracer"}
    iterations = 1
    acc = derive_random_account()

    def process(w3):
        # fund new sender to deploy contract with same address
        fund_acc(w3, acc)
        contract = deploy_contract(w3, CONTRACTS["TestMessageCall"], key=acc.key)
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
        tx = create_contract_transaction(w3, CONTRACTS["TestMessageCall"], key=acc.key)
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


@pytest.mark.skip(reason="skipping onlyTopCall")
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
        _, tx = deploy_contract(w3, CONTRACTS["TestERC20A"], key=acc.key)
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


@pytest.mark.skip(reason="skipping onlyTopCall")
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
        contract = deploy_contract(w3, CONTRACTS["TestMessageCall"], key=acc.key)
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


@pytest.mark.flaky(max_runs=5)
def test_destruct(mantra):
    method = "debug_traceTransaction"
    tracer = {"tracer": "callTracer"}
    receiver = "0x0F0cb39319129BA867227e5Aae1abe9e7dd5f861"
    acc = derive_new_account(11)
    w3 = mantra.w3
    fund_acc(w3, acc, fund=3077735635376769427)
    sender = acc.address
    raw_transactions = []
    contracts = []
    total = 3
    for _ in range(total):
        contract = deploy_contract(w3, CONTRACTS["SelfDestruct"], key=acc.key)
        contracts.append(contract)

    nonce = w3.eth.get_transaction_count(sender)

    for i in range(total):
        tx = (
            contracts[i]
            .functions.execute()
            .build_transaction(
                {
                    "from": sender,
                    "nonce": nonce,
                    "gas": 167115,
                    "gasPrice": 5050000000000,
                    "value": 353434350000000000,
                }
            )
        )
        raw_transactions.append(sign_transaction(w3, tx, acc.key).raw_transaction)
        nonce += 1
    sended_hash_set = send_raw_transactions(w3, raw_transactions)

    def wait_balance():
        return w3.eth.get_balance(receiver) > 0

    wait_for_fn("wait_balance", wait_balance)
    for h in sended_hash_set:
        tx_hash = h.hex()
        tx_hash = f"0x{tx_hash}"
        res = w3.provider.make_request(
            method,
            [tx_hash, tracer],
        )
        assert "insufficient funds" not in res, res

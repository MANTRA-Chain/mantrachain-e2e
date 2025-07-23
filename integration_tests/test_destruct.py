import pytest

from .utils import (
    CONTRACTS,
    deploy_contract,
    derive_new_account,
    fund_acc,
    send_raw_transactions,
    sign_transaction,
    wait_for_fn,
)


@pytest.mark.flaky(max_runs=5)
def test_destruct(mantra):
    method = "debug_traceTransaction"
    tracer = {"tracer": "callTracer"}
    receiver = "0x0F0cb39319129BA867227e5Aae1abe9e7dd5f861"
    acc = derive_new_account(11)  # mantra15jgchufp4kd0z9as2z6ssudcpjghghv3jme0u4
    w3 = mantra.w3
    fund_acc(w3, acc)
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
        res = w3.provider.make_request(
            method,
            [tx_hash, tracer],
        )
        assert "insufficient funds" not in res, res

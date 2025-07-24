import pytest
import web3
from web3 import Web3

from .utils import (
    ADDRS,
    CONTRACTS,
    deploy_contract,
    send_transaction,
    w3_wait_for_new_blocks,
    wait_for_new_blocks,
)


@pytest.mark.skip(reason="fixed in v5")
def test_get_logs_by_topic(mantra):
    w3: Web3 = mantra.w3
    contract = deploy_contract(w3, CONTRACTS["Greeter"])
    topic = f"0x{Web3.keccak(text='ChangeGreeting(address,string)').hex()}"
    tx = contract.functions.setGreeting("world").build_transaction()
    receipt = send_transaction(w3, tx)
    assert receipt.status == 1

    current = w3.eth.block_number
    invalid_block_msg = "invalid block range params"
    # invalid block ranges
    test_cases = [
        {"fromBlock": hex(2000), "toBlock": "latest", "address": [contract.address]},
        {"fromBlock": hex(2), "toBlock": hex(1), "address": [contract.address]},
        {
            "fromBlock": "earliest",
            "toBlock": hex(current + 200),
            "address": [contract.address],
        },
        {
            "fromBlock": hex(current + 20),
            "toBlock": hex(current + 200),
            "address": [contract.address],
        },
    ]

    for params in test_cases:
        with pytest.raises(web3.exceptions.Web3RPCError) as exc:
            w3.eth.get_logs(params)
        assert invalid_block_msg in str(exc.value)

    # log exists
    logs = w3.eth.get_logs({"topics": [topic]})
    assert len(logs) == 1
    assert logs[0]["address"] == contract.address

    # Wait and confirm log doesn't appear in new blocks
    w3_wait_for_new_blocks(w3, 2)
    assert len(w3.eth.get_logs({"topics": [topic]})) == 0

    previous = current
    current = w3.eth.block_number
    # valid block ranges
    valid_cases = [
        {"fromBlock": "earliest", "toBlock": "latest", "address": [contract.address]},
        {
            "fromBlock": "earliest",
            "toBlock": hex(current),
            "address": [contract.address],
        },
        {
            "fromBlock": hex(previous),
            "toBlock": "latest",
            "address": [contract.address],
        },
        {
            "fromBlock": hex(previous),
            "toBlock": hex(current),
            "address": [contract.address],
        },
    ]
    for params in valid_cases:
        logs = w3.eth.get_logs(params)
        assert len(logs) > 0


def test_pending_transaction_filter(mantra):
    w3: Web3 = mantra.w3
    flt = w3.eth.filter("pending")
    assert flt.get_new_entries() == []
    receipt = send_transaction(w3, {"to": ADDRS["community"], "value": 1000})
    assert receipt.status == 1
    assert receipt["transactionHash"] in flt.get_new_entries()


def test_block_filter(mantra):
    w3: Web3 = mantra.w3
    flt = w3.eth.filter("latest")
    # new blocks
    wait_for_new_blocks(mantra.cosmos_cli(), 1, sleep=0.1)
    receipt = send_transaction(w3, {"to": ADDRS["community"], "value": 1000})
    assert receipt.status == 1
    blocks = flt.get_new_entries()
    assert len(blocks) >= 1


def test_event_log_filter(mantra):
    w3: Web3 = mantra.w3
    mycontract = deploy_contract(w3, CONTRACTS["Greeter"])
    assert "Hello" == mycontract.caller.greet()
    current_height = hex(w3.eth.get_block_number())
    event_filter = mycontract.events.ChangeGreeting.create_filter(
        from_block=current_height
    )

    tx = mycontract.functions.setGreeting("world").build_transaction()
    tx_receipt = send_transaction(w3, tx)
    log = mycontract.events.ChangeGreeting().process_receipt(tx_receipt)[0]
    assert log["event"] == "ChangeGreeting"
    assert tx_receipt.status == 1
    new_entries = event_filter.get_new_entries()
    assert len(new_entries) == 1
    print(f"get event: {new_entries}")
    assert new_entries[0] == log
    assert "world" == mycontract.caller.greet()
    # without new txs since last call
    assert event_filter.get_new_entries() == []
    assert event_filter.get_all_entries() == new_entries
    # Uninstall
    assert w3.eth.uninstall_filter(event_filter.filter_id)
    assert not w3.eth.uninstall_filter(event_filter.filter_id)

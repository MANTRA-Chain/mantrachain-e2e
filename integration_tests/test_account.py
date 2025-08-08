import pytest
import web3

from .utils import (
    ADDRS,
    KEYS,
    assert_duplicate,
    derive_new_account,
    send_transaction,
    w3_wait_for_new_blocks,
)


@pytest.mark.connect
def test_connect_transaction_count(connect_mantra):
    test_transaction_count(None, connect_mantra)


def test_transaction_count(mantra, connect_mantra):
    w3 = connect_mantra.w3
    blk = hex(w3.eth.block_number)
    name = "community"
    sender = ADDRS[name]
    receiver = derive_new_account().address
    n0 = w3.eth.get_transaction_count(receiver, blk)
    # ensure transaction send in new block
    w3_wait_for_new_blocks(w3, 1, sleep=0.1)
    receipt = send_transaction(
        w3,
        {
            "from": sender,
            "to": receiver,
            "value": 1000,
        },
        KEYS[name],
    )
    assert receipt.status == 1
    [n1, n2] = [w3.eth.get_transaction_count(receiver, b) for b in [blk, "latest"]]
    assert n0 == n1
    assert n0 == n2
    assert_duplicate(connect_mantra.rpc, receipt.blockNumber)


@pytest.mark.connect
def test_connect_future_blk(connect_mantra):
    test_future_blk(None, connect_mantra)


def test_future_blk(mantra, connect_mantra):
    w3 = connect_mantra.w3
    acc = derive_new_account(2).address
    current = w3.eth.block_number
    future = current + 1000
    with pytest.raises(web3.exceptions.Web3RPCError) as exc:
        w3.eth.get_transaction_count(acc, hex(future))
    assert "cannot query with height in the future" in str(exc)

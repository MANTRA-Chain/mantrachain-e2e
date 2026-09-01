"""eth_getTransactionReceipt answers promptly, null for an unmined tx."""

import time
from pathlib import Path

import pytest
import requests
import web3
from eth_account import Account
from web3._utils.transactions import fill_transaction_defaults

from .network import setup_custom_mantra
from .utils import ADDRS, KEYS, send_transaction

pytestmark = pytest.mark.slow

MATRIX = {
    "indexer-on-mempool-on": 27700,
    "indexer-on-mempool-off": 27800,
    "indexer-off-mempool-on": 27900,
    "indexer-off-mempool-off": 28000,
}
PROMPT = 0.5
CLIENT_TIMEOUT = 70  # past the node's 30s http-timeout


@pytest.fixture(scope="module", params=list(MATRIX))
def matrix(request):
    return request.param


@pytest.fixture(scope="module")
def node(matrix, tmp_path_factory):
    path = tmp_path_factory.mktemp(matrix)
    cfg = Path(__file__).parent / f"configs/receipt-{matrix}.jsonnet"
    yield from setup_custom_mantra(path, MATRIX[matrix], cfg, chain="evmd")


def raw_receipt(node, tx_hash):
    "(result, elapsed) over raw http, bypassing the receipt middleware"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getTransactionReceipt",
        "params": [tx_hash],
    }
    start = time.monotonic()
    rsp = requests.post(node.w3_http_endpoint(0), json=payload, timeout=CLIENT_TIMEOUT)
    elapsed = time.monotonic() - start
    body = rsp.json()
    assert "error" not in body, body["error"]
    return body["result"], elapsed


def nonce_gap_tx(w3, key):
    acct = Account.from_key(key)
    tx = fill_transaction_defaults(
        w3,
        {"from": acct.address, "to": ADDRS["community"], "value": 1, "gas": 21000},
    )
    tx["nonce"] = w3.eth.get_transaction_count(acct.address) + 1
    return acct.sign_transaction(tx)


def test_unknown_hash(node):
    result, elapsed = raw_receipt(node, "0x" + "ab" * 32)
    assert result is None
    assert elapsed < PROMPT, f"null took {elapsed:.2f}s"


def test_mined_tx(node):
    w3 = node.w3
    receipt = send_transaction(w3, {"to": ADDRS["signer1"], "value": 1000})
    result, elapsed = raw_receipt(node, w3.to_hex(receipt["transactionHash"]))
    assert result is not None
    assert elapsed < PROMPT, f"receipt took {elapsed:.2f}s"


def test_queued_tx(node, matrix):
    w3 = node.w3
    signed = nonce_gap_tx(w3, KEYS["signer2"])
    mempool_on = matrix.endswith("mempool-on")
    try:
        w3.eth.send_raw_transaction(signed.raw_transaction)
    except web3.exceptions.Web3RPCError as e:
        assert not mempool_on, e
        pytest.skip("no app-side mempool to queue in")
    assert mempool_on, "nonce-gap tx accepted without an app-side mempool"
    status = w3.provider.make_request("txpool_status", [])["result"]
    assert int(status["queued"], 16) >= 1, status

    result, elapsed = raw_receipt(node, w3.to_hex(signed.hash))
    assert result is None
    assert elapsed < PROMPT, f"null took {elapsed:.2f}s"

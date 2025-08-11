from pathlib import Path

import pytest
from eth_contract.create2 import CREATE2_FACTORY
from eth_utils import to_checksum_address
from hexbytes import HexBytes
from web3.exceptions import Web3RPCError

from .network import setup_custom_mantra
from .utils import send_transaction


@pytest.fixture(scope="module")
def mantra_replay(tmp_path_factory):
    path = tmp_path_factory.mktemp("mantra-replay")
    yield from setup_custom_mantra(
        path, 26400, Path(__file__).parent / "configs/default.jsonnet"
    )


def test_replay_tx(mantra_replay):
    w3 = mantra_replay.w3
    tx = HexBytes(
        "0xf8a58085174876e800830186a08080b853604580600e600039806000f350fe7"
        "fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
        "e03601600081602082378035828234f58015156039578182fd5b80825250505"
        "06014600cf31ba0222222222222222222222222222222222222222222222222"
        "2222222222222222a0222222222222222222222222222222222222222222222"
        "2222222222222222222"
    )
    signer = to_checksum_address("0x3fab184622dc19b6109349b94811493bf2a45362")

    fee = 10**17
    if w3.eth.get_balance(signer) < fee:
        send_transaction(w3, {"to": signer, "value": fee})
    txhash = w3.eth.send_raw_transaction(tx)
    receipt = w3.eth.wait_for_transaction_receipt(txhash)
    assert receipt["status"] == 1
    assert to_checksum_address(receipt["contractAddress"]) == CREATE2_FACTORY


def test_wrong_chain_id(mantra_replay):
    w3 = mantra_replay.w3
    recipient = to_checksum_address("0x3fab184622dc19b6109349b94811493bf2a45362")
    with pytest.raises(Web3RPCError, match="invalid chain id"):
        send_transaction(
            w3, {"to": recipient, "value": 1000, "chainId": 0, "gas": 21000}
        )

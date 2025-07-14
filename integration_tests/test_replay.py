from pathlib import Path
from hexbytes import HexBytes
import pytest
from eth_utils import to_checksum_address

from .network import setup_custom_mantra
from .utils import send_transaction, KEYS

@pytest.fixture(scope="module")
def mantra_replay(tmp_path_factory):
    path = tmp_path_factory.mktemp("mantra-replay")
    yield from setup_custom_mantra(
        path, 26400, Path(__file__).parent / "configs/allow_replay.jsonnet"
    )


def test_replay_tx(mantra_replay):
    w3 = mantra_replay.w3
    address = to_checksum_address('0x4e59b44847b379578588920ca78fbf26c0b4956c')
    tx = HexBytes('0xf8a58085174876e800830186a08080b853604580600e600039806000f350fe7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe03601600081602082378035828234f58015156039578182fd5b8082525050506014600cf31ba02222222222222222222222222222222222222222222222222222222222222222a02222222222222222222222222222222222222222222222222222222222222222')
    signer = to_checksum_address('0x3fab184622dc19b6109349b94811493bf2a45362')

    fee = 10**17
    if w3.eth.get_balance(signer) < fee:
        send_transaction(w3, {
            "to": signer,
            "value": fee,
        }, key=KEYS["validator"])
    txhash = w3.eth.send_raw_transaction(tx)
    receipt = w3.eth.wait_for_transaction_receipt(txhash)
    assert receipt['status'] == 1
    assert to_checksum_address(receipt['contractAddress']) == address

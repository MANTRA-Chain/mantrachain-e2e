import struct
from pathlib import Path

import pytest
import rlp
from eth_hash.auto import keccak
from eth_keys import keys
from eth_rlp import HashableRLP
from pystarport.ledger import ZEMU_API_PORT, Ledger
from pystarport.ledger_utils import (
    LedgerAPDU,
    LedgerButton,
    ethereum_transaction_automation,
)
from rlp.sedes import big_endian_int, binary

from .network import setup_custom_mantra
from .utils import bech32_to_eth

pytestmark = pytest.mark.slow
pytest.skip("wait next bump deps", allow_module_level=True)


class EthereumTransaction(HashableRLP):
    fields = (
        ("nonce", big_endian_int),
        ("gasPrice", big_endian_int),
        ("gas", big_endian_int),
        ("to", binary),
        ("value", big_endian_int),
        ("data", binary),
        ("v", big_endian_int),
        ("r", big_endian_int),
        ("s", big_endian_int),
    )


@pytest.fixture(scope="module")
def custom_mantra(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp("hw_evm")
    ledger = Ledger(elf_file="app_evm.elf", model="nanosp")
    ledger.start()
    assert ledger.is_running(), "Failed to start Ledger simulator"
    try:
        yield from setup_custom_mantra(
            path,
            27300,
            Path(__file__).parent / "configs/hw_evm.jsonnet",
            chain=chain,
        )
    finally:
        try:
            ledger.stop()
        except Exception as e:
            print(f"Error during ledger cleanup: {e}")


def recover_sender(tx_hash, v, r, s):
    recovery_id = (v - 35) % 2 if v >= 35 else v
    signature = keys.Signature(vrs=(recovery_id, r, s))
    pubkey = signature.recover_public_key_from_msg_hash(tx_hash)
    address = keccak(pubkey.to_bytes())[12:].hex()
    return "0x" + address


def pack_derivation_path(path="44'/60'/0'/0/0"):
    elements = path.split("/")
    path_data = struct.pack(">B", len(elements))
    for el in elements:
        hardened = 0x80000000 if el.endswith("'") else 0
        el_val = int(el.rstrip("'")) + hardened
        path_data += struct.pack(">I", el_val)
    return path_data


def sign_tx(w3, tx_params):
    tx = {
        "nonce": w3.eth.get_transaction_count(tx_params["from"]),
        "gasPrice": tx_params["gasPrice"],
        "gas": tx_params.get("gas"),
        "to": bytes.fromhex(tx_params["to"].replace("0x", "")),
        "value": tx_params["value"],
        "data": tx_params.get("data", b""),
        "v": w3.eth.chain_id,
        "r": 0,
        "s": 0,
    }
    unsigned_tx_rlp = rlp.encode(EthereumTransaction.from_dict(tx))
    tx_hash = keccak(unsigned_tx_rlp)
    path_data = pack_derivation_path()
    apdu_payload = path_data + unsigned_tx_rlp
    apdu = (
        struct.pack(">BBBBB", 0xE0, 0x04, 0x00, 0x00, len(apdu_payload)) + apdu_payload
    )

    apdu_client = LedgerAPDU(ZEMU_API_PORT)
    btn_client = LedgerButton()

    def automation(apdu_complete):
        ethereum_transaction_automation(btn_client, apdu_complete)

    response = apdu_client.send_apdu_with_automation(apdu.hex(), automation, timeout=60)
    if not LedgerAPDU.is_success(response) or len(response) - 2 != 65:
        return None

    expected_sender = tx_params["from"].lower()
    r = int.from_bytes(response[1:33], "big")
    s = int.from_bytes(response[33:65], "big")
    for recovery_id in [0, 1]:
        eip155_v = recovery_id + (w3.eth.chain_id * 2) + 35
        recovered = recover_sender(tx_hash, eip155_v, r, s)
        if recovered.lower() == expected_sender:
            break
    else:
        raise ValueError("recover sender fails")
    signed_tx = EthereumTransaction.from_dict({**tx, "v": eip155_v, "r": r, "s": s})
    return {
        "rawTransaction": rlp.encode(signed_tx),
        "hash": signed_tx.hash(),
        "v": eip155_v,
        "r": r,
        "s": s,
    }


def test_ledger(custom_mantra):
    cli = custom_mantra.cosmos_cli()
    w3 = custom_mantra.w3
    hw = cli.address("hw")
    assert cli.balance(hw) == 8000
    tx = {
        "from": bech32_to_eth(hw),
        "to": bech32_to_eth(cli.address("community")),
        "value": 4000,
        "gas": 21000,
        "gasPrice": w3.eth.gas_price,
    }
    signed_tx = sign_tx(w3, tx)
    txhash = w3.eth.send_raw_transaction(signed_tx["rawTransaction"])
    receipt = w3.eth.wait_for_transaction_receipt(txhash)
    assert receipt["status"] == 1

import base64
import json

import pytest
import requests
from eth_account import Account
from pystarport import ports

from .eip712_utils import (
    TxRaw,
    create_message_send,
    create_tx_raw_eip712,
    encode_eip712_for_signing,
    signature_to_web3_extension,
)
from .utils import ADDRS, CHAIN_ID, DEFAULT_DENOM, KEYS

pytest.skip("wait enable in ante handler", allow_module_level=True)


def _broadcast_tx(mantra, tx_bytes_b64):
    p = ports.api_port(mantra.base_port(0))
    url = f"http://127.0.0.1:{p}/cosmos/tx/v1beta1/txs"
    body = {"tx_bytes": tx_bytes_b64, "mode": "BROADCAST_MODE_SYNC"}
    rsp = requests.post(url, json=body)
    if not rsp.ok:
        raise Exception(f"response code: {rsp.status_code}, {rsp.reason}, {rsp.json()}")
    return rsp.json()["tx_response"]


def _common_setup(mantra):
    cli = mantra.cosmos_cli()
    w3 = mantra.w3
    chain = {"chainId": w3.eth.chain_id, "cosmosChainId": CHAIN_ID}
    src = "community"
    src_addr = cli.address(src)
    acc = cli.account(src_addr)
    sender = {
        "accountAddress": src_addr,
        "sequence": w3.eth.get_transaction_count(ADDRS[src]),
        "accountNumber": int(acc["account"]["value"]["account_number"]),
        "pubkey": json.loads(cli.address(src, "acc", "pubkey"))["key"],
    }
    dst_addr = cli.address("signer1")
    gas = 200000
    gas_price = 100000000000  # default base fee
    fee = {
        "amount": str(gas * gas_price),
        "denom": DEFAULT_DENOM,
        "gas": str(gas),
    }
    params = {
        "destinationAddress": dst_addr,
        "amount": "1",
        "denom": DEFAULT_DENOM,
    }
    return cli, chain, src, sender, fee, params, gas


def _sign_eip712(chain, sender, fee, params, src):
    tx = create_message_send(chain, sender, fee, "", params)
    msg_hash = encode_eip712_for_signing(tx["eipToSign"])
    signed = Account.unsafe_sign_hash(msg_hash, KEYS[src])
    return tx, signed.signature


def test_without_extension(mantra):
    cli, chain, src, sender, fee, params, gas = _common_setup(mantra)
    tx, sig = _sign_eip712(chain, sender, fee, params, src)

    legacy = tx["legacyAmino"]
    signed_tx = TxRaw(
        body_bytes=legacy["body"].SerializeToString(),
        auth_info_bytes=legacy["authInfo"].SerializeToString(),
        signatures=[sig],
    )

    tx_bytes_b64 = base64.b64encode(signed_tx.SerializeToString()).decode("utf-8")
    rsp = _broadcast_tx(mantra, tx_bytes_b64)
    assert rsp["code"] == 0, rsp["raw_log"]

    events = cli.event_query_tx_for(rsp["txhash"])
    assert events["gas_wanted"] == str(gas)


def test_native_tx(mantra):
    cli, chain, src, sender, fee, params, gas = _common_setup(mantra)
    tx, sig = _sign_eip712(chain, sender, fee, params, src)

    extension = signature_to_web3_extension(chain, sender, sig)
    legacy = tx["legacyAmino"]
    signed_tx = create_tx_raw_eip712(legacy["body"], legacy["authInfo"], extension)

    tx_bytes_b64 = base64.b64encode(signed_tx["message"].SerializeToString()).decode(
        "utf-8"
    )
    rsp = _broadcast_tx(mantra, tx_bytes_b64)
    assert rsp["code"] == 0, rsp["raw_log"]

    events = cli.event_query_tx_for(rsp["txhash"])
    assert events["gas_wanted"] == str(gas)

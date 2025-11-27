import base64
import json

import pytest
import requests
from eth_account import Account
from eth_account.messages import encode_typed_data
from pystarport import ports

from .eip712_utils import (
    create_message_send,
    create_tx_raw_eip712,
    signature_to_web3_extension,
)
from .utils import ADDRS, CHAIN_ID, DEFAULT_DENOM, KEYS

pytest.skip("wait enable in ante handler", allow_module_level=True)


def test_native_tx(mantra):
    cli = mantra.cosmos_cli()
    w3 = mantra.w3
    chain_id = w3.eth.chain_id
    chain = {
        "chainId": chain_id,
        "cosmosChainId": CHAIN_ID,
    }
    src = "community"
    src_addr = cli.address(src)
    src_account = cli.account(src_addr)
    sender = {
        "accountAddress": src_addr,
        "sequence": w3.eth.get_transaction_count(ADDRS[src]),
        "accountNumber": int(src_account["account"]["value"]["account_number"]),
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
    amount = "1"
    params = {
        "destinationAddress": dst_addr,
        "amount": amount,
        "denom": DEFAULT_DENOM,
    }
    tx = create_message_send(chain, sender, fee, "", params)
    structured_msg = encode_typed_data(full_message=tx["eipToSign"])
    signed = Account.sign_message(structured_msg, KEYS[src])
    extension = signature_to_web3_extension(
        chain,
        sender,
        signed.signature,
    )
    legacy_amino = tx["legacyAmino"]
    signed_tx = create_tx_raw_eip712(
        legacy_amino["body"],
        legacy_amino["authInfo"],
        extension,
    )
    tx_bytes = base64.b64encode(signed_tx["message"].SerializeToString())
    body = {
        "tx_bytes": tx_bytes.decode("utf-8"),
        "mode": "BROADCAST_MODE_SYNC",
    }
    p = ports.api_port(mantra.base_port(0))
    url = f"http://127.0.0.1:{p}/cosmos/tx/v1beta1/txs"
    response = requests.post(url, json=body)
    if not response.ok:
        raise Exception(
            f"response code: {response.status_code}, "
            f"{response.reason}, {response.json()}"
        )
    rsp = response.json()["tx_response"]
    assert rsp["code"] == 0, rsp["raw_log"]
    rsp = cli.event_query_tx_for(rsp["txhash"])
    assert rsp["gas_wanted"] == str(gas)

import base64
import json

import pytest
import requests
from eth_account import Account
from pystarport import ports

from .cosmostx_utils import (
    EPubKey,
    LegacyAminoPubKey,
    MultiSignature,
    ProtoAny,
    TxRaw,
    create_multisig_auth_info,
)
from .eip712_utils import (
    create_message_send,
    create_tx_raw_eip712,
    encode_eip712_for_signing,
    signature_to_web3_extension,
)
from .utils import ADDRS, CHAIN_ID, DEFAULT_DENOM, KEYS


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


@pytest.mark.skip(reason="wait enable in ante handler")
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


def test_multisig_eip712(mantra):
    cli = mantra.cosmos_cli()
    w3 = mantra.w3
    signer1_name = "community"
    signer2_name = "signer1"
    signer1_addr = cli.address(signer1_name)

    # 2-of-2 multisig account
    multisig_name = "test_multisig_eip712"
    cli.make_multisig(multisig_name, signer1_name, signer2_name)
    multisig_addr = cli.address(multisig_name)

    fund_amt = 1_000_000_000_000_000_000
    rsp = cli.transfer(signer1_addr, multisig_addr, f"{fund_amt}{DEFAULT_DENOM}")
    assert rsp["code"] == 0, rsp["raw_log"]

    multisig_acc = cli.account(multisig_addr)
    multisig_account_number = int(multisig_acc["account"]["value"]["account_number"])
    multisig_sequence = int(multisig_acc["account"]["value"].get("sequence", 0))

    multisig_pubkey_info = json.loads(cli.address(multisig_name, "acc", "pubkey"))
    threshold = multisig_pubkey_info["threshold"]
    chain = {"chainId": w3.eth.chain_id, "cosmosChainId": CHAIN_ID}
    gas = 200000
    gas_price = 100000000000
    fee = {
        "amount": str(gas * gas_price),
        "denom": DEFAULT_DENOM,
        "gas": str(gas),
    }

    dst_addr = cli.address("signer2")
    params = {
        "destinationAddress": dst_addr,
        "amount": "1000",
        "denom": DEFAULT_DENOM,
    }

    signer1_pubkey = json.loads(cli.address(signer1_name, "acc", "pubkey"))["key"]
    signer2_pubkey = json.loads(cli.address(signer2_name, "acc", "pubkey"))["key"]

    pub_key_msgs = []
    for pubkey in [signer1_pubkey, signer2_pubkey]:
        pubkey_decoded = base64.b64decode(pubkey.encode("ascii"))
        pub_key_msg = EPubKey(key=pubkey_decoded)
        pub_key_any = ProtoAny(
            type_url="/cosmos.evm.crypto.v1.ethsecp256k1.PubKey",
            value=pub_key_msg.SerializeToString(),
        )
        pub_key_msgs.append(pub_key_any.SerializeToString())

    legacy_amino_pubkey = LegacyAminoPubKey(
        threshold=int(threshold), public_keys=pub_key_msgs
    )
    multisig_pubkey_any = ProtoAny(
        type_url="/cosmos.crypto.multisig.LegacyAminoPubKey",
        value=legacy_amino_pubkey.SerializeToString(),
    )

    def sign_for_multisig(signer_name, signer_key):
        sender = {
            "accountAddress": multisig_addr,
            "sequence": multisig_sequence,
            "accountNumber": multisig_account_number,
            "pubkey": json.loads(cli.address(signer_name, "acc", "pubkey"))["key"],
        }

        tx = create_message_send(chain, sender, fee, "", params)
        msg_hash = encode_eip712_for_signing(tx["eipToSign"])
        signed = Account.unsafe_sign_hash(msg_hash, signer_key)
        return tx, signed.signature

    tx1, sig1 = sign_for_multisig(signer1_name, KEYS[signer1_name])
    _, sig2 = sign_for_multisig(signer2_name, KEYS[signer2_name])

    legacy = tx1["legacyAmino"]

    auth_info = create_multisig_auth_info(
        multisig_pubkey_any=multisig_pubkey_any,
        sequence=multisig_sequence,
        fee_amount=fee["amount"],
        fee_denom=fee["denom"],
        gas_limit=fee["gas"],
        num_signers=2,
    )

    multi_sig = MultiSignature(signatures=[sig1, sig2])
    signed_tx = TxRaw(
        body_bytes=legacy["body"].SerializeToString(),
        auth_info_bytes=auth_info.SerializeToString(),
        signatures=[multi_sig.SerializeToString()],
    )

    tx_bytes_b64 = base64.b64encode(signed_tx.SerializeToString()).decode("utf-8")
    rsp = _broadcast_tx(mantra, tx_bytes_b64)
    assert rsp["code"] == 0, rsp["raw_log"]

    events = cli.event_query_tx_for(rsp["txhash"])
    assert events["gas_wanted"] == str(gas)

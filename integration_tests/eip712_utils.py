import base64
import json
from pathlib import Path

from eth_abi import encode as abi_encode
from eth_account._utils.encode_typed_data.encoding_and_hashing import (
    encode_data,
    get_primary_type,
    hash_type,
)
from eth_utils import keccak as eth_keccak

from .cosmostx_utils import (
    LEGACY_AMINO,
    AuthInfo,
    Coin,
    EPubKey,
    ExtensionOptionsWeb3Tx,
    Fee,
    ModeInfo,
    ModeInfoSingle,
    MsgSend,
    ProtoAny,
    SignerInfo,
    TxBody,
    TxRaw,
)


def create_message_send(chain, sender, fee, memo, params):
    "A MsgSend as EIP-712 typed data, plus its legacy-amino tx body and auth info."
    amount = [{"amount": params["amount"], "denom": params["denom"]}]
    msg = {
        "type": "cosmos-sdk/MsgSend",
        "value": {
            "amount": amount,
            "from_address": sender["accountAddress"],
            "to_address": params["destinationAddress"],
        },
    }
    eip_to_sign = {
        "types": json.loads(
            (Path(__file__).parent / "msg_send_types.json").read_text()
        ),
        "primaryType": "Tx",
        "domain": {
            "name": "Cosmos Web3",
            "version": "1.0.0",
            "chainId": chain["chainId"],
            "verifyingContract": "cosmos",
            "salt": "0",
        },
        "message": {
            "account_number": str(sender["accountNumber"]),
            "chain_id": chain["cosmosChainId"],
            "fee": {
                "amount": [{"amount": fee["amount"], "denom": fee["denom"]}],
                "gas": fee["gas"],
                "feePayer": sender["accountAddress"],
            },
            "memo": memo,
            "msgs": [msg],
            "sequence": str(sender["sequence"]),
        },
    }

    msg_send = MsgSend(
        from_address=sender["accountAddress"],
        to_address=params["destinationAddress"],
        amount=[Coin(denom=params["denom"], amount=params["amount"])],
    )
    body = TxBody(
        memo=memo,
        messages=[
            ProtoAny(
                type_url="/cosmos.bank.v1beta1.MsgSend",
                value=msg_send.SerializeToString(),
            ).SerializeToString()
        ],
    )
    pubkey = EPubKey(key=base64.b64decode(sender["pubkey"].encode("ascii")))
    mode_info = ModeInfo(single=ModeInfoSingle(mode=LEGACY_AMINO).SerializeToString())
    signer_info = SignerInfo(
        mode_info=mode_info.SerializeToString(),
        sequence=sender["sequence"],
        public_key=ProtoAny(
            type_url="/cosmos.evm.crypto.v1.ethsecp256k1.PubKey",
            value=pubkey.SerializeToString(),
        ).SerializeToString(),
    )
    fee_message = Fee(
        gas_limit=int(fee["gas"]),
        amount=[Coin(denom=fee["denom"], amount=fee["amount"])],
    )
    auth_info = AuthInfo(
        signer_infos=[signer_info.SerializeToString()],
        fee=fee_message.SerializeToString(),
    )
    return {
        "legacyAmino": {"body": body, "authInfo": auth_info},
        "eipToSign": eip_to_sign,
    }


def encode_eip712_for_signing(eip712_data):
    # manually hash the domain with custom encoding to allow "cosmos" as string
    # https://github.com/cosmos/evm/blob/8f242bfec51ae3b80e9473312f84935b2a34d94b/ethereum/eip712/domain.go#L14
    domain_data = eip712_data["domain"]
    types = eip712_data["types"]
    domain_types = {
        "EIP712Domain": [
            {"name": "name", "type": "string"},
            {"name": "version", "type": "string"},
            {"name": "chainId", "type": "uint256"},
            {
                "name": "verifyingContract",
                "type": "string",
            },  # string instead of address
            {"name": "salt", "type": "string"},
        ]
    }

    domain_type_hash = hash_type("EIP712Domain", domain_types)
    domain_values = [
        eth_keccak(text=domain_data["name"]),
        eth_keccak(text=domain_data["version"]),
        domain_data["chainId"],
        eth_keccak(
            text=domain_data["verifyingContract"]
        ),  # verifyingContract as string
        eth_keccak(text=domain_data["salt"]),
    ]
    encoded_domain = abi_encode(
        ["bytes32", "bytes32", "bytes32", "uint256", "bytes32", "bytes32"],
        [domain_type_hash] + domain_values,
    )
    domain_separator = eth_keccak(encoded_domain)
    message_types = {k: v for k, v in types.items() if k != "EIP712Domain"}
    primary_type = eip712_data.get("primaryType") or get_primary_type(message_types)
    message_hash = eth_keccak(
        encode_data(primary_type, message_types, eip712_data["message"])
    )
    signable = b"\x19\x01" + domain_separator + message_hash
    return eth_keccak(signable)


def signature_to_web3_extension(chain, sender, signature):
    message = ExtensionOptionsWeb3Tx(
        typed_data_chain_id=chain["chainId"],
        fee_payer=sender["accountAddress"],
        fee_payer_sig=signature,
    )
    return ProtoAny(
        type_url="/cosmos.evm.eip712.v1.ExtensionOptionsWeb3Tx",
        value=message.SerializeToString(),
    )


def create_tx_raw_eip712(body, auth_info, extension):
    body.extension_options.append(extension.SerializeToString())
    return TxRaw(
        body_bytes=body.SerializeToString(),
        auth_info_bytes=auth_info.SerializeToString(),
        signatures=[bytes()],
    )

from __future__ import annotations

import base64

from cprotobuf import Field, ProtoEntity
from eth_account import Account
from eth_keys import keys as eth_keys
from eth_utils import keccak as eth_keccak
from pystarport.utils import wait_for_new_blocks

from .cosmostx_utils import (
    SIGN_DIRECT,
    Coin,
    ProtoAny,
    TxBody,
    TxRaw,
)
from .eip712_utils import (
    create_auth_info,
    create_fee,
    create_sig_doc,
    create_signer_info,
)
from .utils import KEYS, broadcast_tx

# ICS20 ABI encoding string — the only encoding solidity-ibc-eureka's
# ICS20Transfer.onRecvPacket accepts (ICS20Lib.ICS20_ENCODING). The CLI can't
# set this, so the Cosmos→EVM return transfer is a hand-built MsgTransfer.
ICS20_ABI_ENCODING = "application/x-solidity-abi"


class _MsgTransfer(ProtoEntity):
    """/ibc.applications.transfer.v1.MsgTransfer. Empty timeout_height (field 6,
    omitted) routes source_channel through channel/v2 for a v2 client."""

    source_port = Field("string", 1)
    source_channel = Field("string", 2)
    token = Field(Coin, 3)
    sender = Field("string", 4)
    receiver = Field("string", 5)
    timeout_timestamp = Field("uint64", 7)  # v2 channel timeouts are SECONDS
    memo = Field("string", 8)
    encoding = Field("string", 9)


# Pubkey proto path for cosmos/evm accounts; matches create_signer_info's
# non-"secp256k1" branch (EPubKey / ethsecp256k1).
_ETHSECP256K1 = "ethsecp256k1"


def sign_and_broadcast_body(
    mantra,
    signer_name: str,
    body_bytes: bytes,
    *,
    denom: str,
    gas: int = 2_000_000,
    gas_price: int = 100_000_000_000,
) -> dict:
    """SIGN_DIRECT-sign ``body_bytes`` (a serialized ``TxBody``) with
    ``signer_name`` and broadcast it. Returns the committed tx (with events);
    raises on non-zero code.
    """
    cli = mantra.cosmos_cli()
    # account_number + sequence from `q auth account` (amino `value` shape, with
    # the EthAccount→base_account nesting; amino omits a zero sequence).
    acc = cli.account(cli.address(signer_name))["account"]["value"]
    base = acc.get("base_account", acc)
    account_number = int(base.get("account_number", 0))
    sequence = int(base.get("sequence", 0))
    # Compressed pubkey straight from the private key (no CLI round-trip).
    pubkey = eth_keys.PrivateKey(KEYS[signer_name]).public_key.to_compressed_bytes()

    signer_info = create_signer_info(_ETHSECP256K1, pubkey, sequence, SIGN_DIRECT)
    auth_info = create_auth_info(
        signer_info, create_fee(str(gas * gas_price), denom, gas)
    )
    sign_doc = create_sig_doc(
        body_bytes, auth_info.SerializeToString(), cli.chain_id, account_number
    )
    # ethsecp256k1.VerifySignature keccak-hashes the SignDoc itself, so sign
    # keccak256(SignDoc) and hand over the raw 65-byte signature.
    digest = eth_keccak(sign_doc.SerializeToString())
    sig = Account.unsafe_sign_hash(digest, KEYS[signer_name]).signature

    tx_raw = TxRaw(
        body_bytes=body_bytes,
        auth_info_bytes=auth_info.SerializeToString(),
        signatures=[bytes(sig)],
    )
    tx_b64 = base64.b64encode(tx_raw.SerializeToString()).decode()
    tx_response = broadcast_tx(mantra, tx_b64)
    if tx_response.get("code", 1) != 0:
        raise RuntimeError(f"broadcast failed: {tx_response.get('raw_log')}")

    # Sync mode returns before inclusion — wait, then re-query for events.
    wait_for_new_blocks(cli, 1)
    tx = cli.event_query_tx_for(tx_response["txhash"])
    return tx


def cosmos_signer(mantra, signer_name: str, *, denom: str):
    """A ``BinaryRelayer`` cosmos_signer: sign + broadcast a relayer-returned
    ``TxBody`` on ``mantra`` with ``signer_name``, returning the committed tx."""
    return lambda body: sign_and_broadcast_body(mantra, signer_name, body, denom=denom)


def send_v2_transfer(
    mantra,
    signer_name: str,
    *,
    source_client: str,
    receiver: str,
    token_denom: str,
    amount: int,
    timeout_timestamp: int,
    fee_denom: str,
    encoding: str = ICS20_ABI_ENCODING,
) -> dict:
    """Initiate an ICS20 IBC v2 transfer from the cosmos chain (ibcRouterV2 SEND
    side): build + SIGN_DIRECT-broadcast a ``MsgTransfer`` with empty timeout
    height (routes through channel/v2) and ABI ``encoding`` (required by solidity
    ICS20Transfer.onRecvPacket). ``token_denom`` is the sender's local denom,
    ``receiver`` the dest-chain address (hex for EVM), ``timeout_timestamp`` in
    SECONDS. Returns the committed cosmos tx (with events).
    """
    sender = mantra.cosmos_cli().address(signer_name)
    msg = _MsgTransfer(
        source_port="transfer",
        source_channel=source_client,
        token=Coin(denom=token_denom, amount=str(amount)),
        sender=sender,
        receiver=receiver,
        timeout_timestamp=int(timeout_timestamp),
        memo="",
        encoding=encoding,
    )
    any_msg = ProtoAny(
        type_url="/ibc.applications.transfer.v1.MsgTransfer",
        value=msg.SerializeToString(),
    )
    body = TxBody(messages=[any_msg.SerializeToString()], memo="")
    return sign_and_broadcast_body(
        mantra, signer_name, body.SerializeToString(), denom=fee_denom
    )


def ibc_voucher_balances(mantra, addr: str) -> dict[str, int]:
    """``{denom: amount}`` for every ``ibc/<HASH>`` voucher the address holds —
    lets a test assert a voucher appeared without recomputing its denom hash."""
    return {
        b["denom"]: int(b["amount"])
        for b in mantra.cosmos_cli().balances(addr)
        if b["denom"].startswith("ibc/")
    }

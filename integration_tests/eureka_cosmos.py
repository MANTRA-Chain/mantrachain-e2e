from __future__ import annotations

import base64
import json
import re
import subprocess
import time

import requests
from cprotobuf import Field, ProtoEntity
from eth_account import Account
from eth_keys import keys as eth_keys
from eth_utils import keccak as eth_keccak
from pystarport import ports
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
from .utils import KEYS

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


# A bech32 account address (``<hrp>1<38+ chars>``), pulled out of CLI output
# that gRPC's atfork logger may have polluted (see conftest.py).
_BECH32_RE = re.compile(r"[a-z]{2,10}1[ac-hj-np-z02-9]{38,}")


def _clean_bech32(raw: str) -> str:
    matches = _BECH32_RE.findall(raw.strip())
    if not matches:
        raise ValueError(f"no bech32 address in CLI output: {raw!r}")
    return matches[-1]


def _first_json(raw: str) -> dict:
    """Parse the first JSON object in ``raw``, skipping any leading log noise."""
    start = raw.find("{")
    if start < 0:
        raise ValueError(f"no JSON object in CLI output: {raw!r}")
    return json.loads(raw[start:])


# Pubkey proto path for cosmos/evm accounts; matches create_signer_info's
# non-"secp256k1" branch (EPubKey / ethsecp256k1).
_ETHSECP256K1 = "ethsecp256k1"


def _api_url(mantra, path: str) -> str:
    p = ports.api_port(mantra.base_port(0))
    return f"http://127.0.0.1:{p}{path}"


def account_info(mantra, addr: str) -> tuple[int, int]:
    """``(account_number, sequence)`` via ``q auth account`` (amino ``value``
    shape, tolerating the ``EthAccount``→``base_account`` nesting). Amino omits
    zero-valued fields, so a fresh signer has no ``sequence`` key — default to 0."""
    acc = mantra.cosmos_cli().account(addr)["account"]["value"]
    base = acc.get("base_account", acc)
    return int(base.get("account_number", 0)), int(base.get("sequence", 0))


def _pubkey_bytes(signer_name: str) -> bytes:
    """Compressed secp256k1 pubkey for ``signer_name``, derived straight from
    the private key (avoids a CLI round-trip that gRPC fork-logging pollutes)."""
    return eth_keys.PrivateKey(KEYS[signer_name]).public_key.to_compressed_bytes()


def _wait_tx_queryable(cli, txhash: str, *, attempts: int = 30, delay: float = 0.5):
    """Block until CometBFT's by-hash ``/tx`` lookup succeeds on the relayer's
    node — its cosmos->eth fetch otherwise fails "tx not found" if it queries
    before the index is populated."""
    h = txhash if txhash.startswith("0x") else "0x" + txhash
    for _ in range(attempts):
        try:
            j = requests.get(
                f"{cli.node_rpc_http}/tx", params={"hash": h}, timeout=5
            ).json()
        except requests.RequestException:
            j = {}
        if (j.get("result") or {}).get("hash"):
            return
        time.sleep(delay)
    raise RuntimeError(f"tx {txhash} not queryable after {attempts} tries")


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
    signer_addr = _clean_bech32(cli.address(signer_name))
    account_number, sequence = account_info(mantra, signer_addr)

    signer_info = create_signer_info(
        _ETHSECP256K1, _pubkey_bytes(signer_name), sequence, SIGN_DIRECT
    )
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
    rsp = requests.post(
        _api_url(mantra, "/cosmos/tx/v1beta1/txs"),
        json={"tx_bytes": tx_b64, "mode": "BROADCAST_MODE_SYNC"},
        timeout=15,
    )
    rsp.raise_for_status()
    tx_response = rsp.json()["tx_response"]
    if tx_response.get("code", 1) != 0:
        raise RuntimeError(f"broadcast failed: {tx_response.get('raw_log')}")

    # Sync mode returns before inclusion — wait, then re-query for events.
    wait_for_new_blocks(cli, 1)
    tx = cli.event_query_tx_for(tx_response["txhash"])
    # event_query_tx_for can return before the by-hash tx index is populated;
    # block until the relayer's ``/tx?hash`` lookup would succeed, else a later
    # cosmos->eth relay of this tx fails with "tx not found".
    _wait_tx_queryable(cli, tx_response["txhash"])
    return tx


def add_counterparty(
    mantra,
    signer_name: str,
    client_id: str,
    counterparty_client_id: str,
    merkle_prefix: list[bytes],
    *,
    denom: str,
    gas: int = 400_000,
    gas_price: int = 100_000_000_000,
) -> None:
    """Register the counterparty for a v2 client via the evmd CLI
    ``tx ibc client add-counterparty`` (merkle-prefix args base64-encoded).

    Uses an argv list, not pystarport's shell-string path: an empty prefix
    element (``[b""]``→``""``) gets dropped by the shell, which the CLI rejects.
    """
    cli = mantra.cosmos_cli()
    prefixes_b64 = [base64.b64encode(p).decode() for p in merkle_prefix]
    cmd = [
        mantra.chain_binary,
        "tx",
        "ibc",
        "client",
        "add-counterparty",
        client_id,
        counterparty_client_id,
        *prefixes_b64,
        "-y",
        "--from",
        signer_name,
        "--home",
        str(cli.data_dir),
        "--keyring-backend",
        "test",
        "--chain-id",
        cli.chain_id,
        "--gas",
        str(gas),
        "--gas-prices",
        f"{gas_price}{denom}",
        "--node",
        mantra.node_rpc(0),
        "--output",
        "json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert (
        proc.returncode == 0
    ), f"add-counterparty failed: {proc.stdout}\n{proc.stderr}"
    rsp = _first_json(proc.stdout)
    assert rsp.get("code", 1) == 0, f"add-counterparty tx failed: {rsp.get('raw_log')}"
    wait_for_new_blocks(cli, 1)


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
    sender = _clean_bech32(mantra.cosmos_cli().address(signer_name))
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

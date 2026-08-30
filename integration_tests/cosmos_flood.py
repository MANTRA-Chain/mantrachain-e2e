"""In-process cosmos bank-send signing + async broadcast_tx_sync flooding.

Sustains a flood (thousands of tx/s) that the CLI path (~150 tx/s) can't, to
saturate the app-side cosmos mempool. See test_mempool_starvation.py.
"""

import asyncio
import base64
from typing import NamedTuple

import aiohttp
import ujson
from eth_hash.auto import keccak
from eth_keys import keys as eth_keys

from .cosmostx_utils import (
    SIGN_DIRECT,
    AuthInfo,
    Coin,
    EPubKey,
    Fee,
    ModeInfo,
    ModeInfoSingle,
    MsgSend,
    ProtoAny,
    SignDoc,
    SignerInfo,
    TxBody,
    TxRaw,
)

ETHSECP256K1_PUBKEY_URL = "/cosmos.evm.crypto.v1.ethsecp256k1.PubKey"
MSG_SEND_URL = "/cosmos.bank.v1beta1.MsgSend"


class SignSpec(NamedTuple):
    """One sender's chain: `count` bank sends, nonces seq0..seq0+count-1."""

    priv: bytes
    from_bech: str
    to_bech: str
    amount: int
    denom: str
    gas: int
    fee: int
    seq0: int
    count: int
    account_number: int
    chain_id: str


def _any(type_url: str, msg) -> ProtoAny:
    return ProtoAny(type_url=type_url, value=msg.SerializeToString())


def address_of(priv: bytes) -> str:
    """Return the 0x eth address for a raw secp256k1 private key."""
    return eth_keys.PrivateKey(priv).public_key.to_checksum_address()


def sign_bank_send(s: SignSpec, sequence: int) -> str:
    """Return a base64-encoded, SIGN_MODE_DIRECT-signed bank MsgSend TxRaw."""
    sk = eth_keys.PrivateKey(s.priv)
    pub = sk.public_key.to_compressed_bytes()

    msg = MsgSend(
        from_address=s.from_bech,
        to_address=s.to_bech,
        amount=[Coin(denom=s.denom, amount=str(s.amount))],
    )
    body = TxBody(messages=[_any(MSG_SEND_URL, msg).SerializeToString()])
    body_bytes = body.SerializeToString()

    signer_info = SignerInfo(
        public_key=_any(ETHSECP256K1_PUBKEY_URL, EPubKey(key=pub)).SerializeToString(),
        mode_info=ModeInfo(
            single=ModeInfoSingle(mode=SIGN_DIRECT).SerializeToString()
        ).SerializeToString(),
        sequence=sequence,
    )
    auth_info = AuthInfo(
        signer_infos=[signer_info.SerializeToString()],
        fee=Fee(
            amount=[Coin(denom=s.denom, amount=str(s.fee))], gas_limit=int(s.gas)
        ).SerializeToString(),
    )
    auth_info_bytes = auth_info.SerializeToString()

    sign_doc = SignDoc(
        body_bytes=body_bytes,
        auth_info_bytes=auth_info_bytes,
        chain_id=s.chain_id,
        account_number=s.account_number,
    )
    # ethsecp256k1 signs keccak256(SignDoc), the tx signature is r||s (drop v)
    sig = sk.sign_msg_hash(keccak(sign_doc.SerializeToString())).to_bytes()[:64]

    raw = TxRaw(
        body_bytes=body_bytes, auth_info_bytes=auth_info_bytes, signatures=[sig]
    )
    return base64.b64encode(raw.SerializeToString()).decode()


def sign_chain(s: SignSpec) -> list[str]:
    "sign one sender's chain; top-level so a ProcessPoolExecutor can pickle it"
    return [sign_bank_send(s, s.seq0 + i) for i in range(s.count)]


# The cosmos pool inserts via one worker, so a few hundred concurrent broadcasts
# already saturate it. One connection per sender (thousands) instead makes a slow
# node reset connections, which looks like starvation but isn't; capped, a
# healthy node sees zero errors, so no retry is needed.
MAX_INFLIGHT = 256


def broadcast_body(tx_b64: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "broadcast_tx_sync",
        "params": {"tx": tx_b64},
    }


async def _broadcast_sync(session, rpc: str, tx_b64: str):
    async with session.post(rpc, json=broadcast_body(tx_b64)) as resp:
        data = await resp.json(loads=ujson.loads)
    result = data.get("result")
    if result is None:
        return -1, str(data.get("error"))
    return int(result["code"]), result.get("log", "")


async def _flood_sender(sem, session, rpc, chain, results):
    """Broadcast one sender's chain in nonce order, each after the prior CheckTx.

    A rejection or connection error abandons the rest of the chain, since a
    starved node stalls CheckTx until the RPC resets.
    """
    for tx_b64 in chain:
        try:
            async with sem:
                code, log = await _broadcast_sync(session, rpc, tx_b64)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            results.append((-1, "connection error"))
            return
        results.append((code, log))
        if code != 0:
            return  # rejected, the rest of this chain can no longer land


async def _run_flood(rpc, chains):
    sem = asyncio.Semaphore(MAX_INFLIGHT)
    conn = aiohttp.TCPConnector(limit=MAX_INFLIGHT)
    async with aiohttp.ClientSession(
        connector=conn,
        json_serialize=ujson.dumps,
        timeout=aiohttp.ClientTimeout(total=30),
    ) as session:
        results: list = []
        await asyncio.gather(
            *(_flood_sender(sem, session, rpc, chain, results) for chain in chains)
        )
        return results


def flood(rpc: str, chains: list[list[str]]) -> list[tuple[int, str]]:
    "broadcast chains concurrently: senders in parallel, each in nonce order"
    return asyncio.run(_run_flood(rpc, chains))

import asyncio
import base64
import itertools
import multiprocessing
import os
import sys
from collections import namedtuple
from pathlib import Path

import aiohttp
import backoff
import eth_abi
import ujson
from hexbytes import HexBytes

from ..cosmostx_utils import (
    AuthInfo,
    Coin,
    Fee,
    MsgEthereumTx,
    TxBody,
    TxRaw,
    build_any,
)
from .erc20 import CONTRACT_ADDRESS
from .utils import (
    DEFAULT_DENOM,
    DEFAULT_EXTENDED_DENOM,
    LOCAL_RPC,
    gen_account,
    split,
    split_batch,
)

GAS_PRICE = 1000000000
CHAIN_ID = 7888
CONNECTION_POOL_SIZE = 1024
TXS_DIR = "txs"

Job = namedtuple(
    "Job",
    [
        "chunk",
        "global_seq",
        "num_txs",
        "tx_type",
        "create_tx",
        "batch",
        "nonce",
        "tx_options",
        "evm_denom",
    ],
)
EthTx = namedtuple("EthTx", ["tx", "raw", "sender"])


def simple_transfer_tx(sender: str, nonce: int, options: dict):
    return {
        "to": sender,
        "value": 1,
        "nonce": nonce,
        "gas": 21000,
        "gasPrice": options.get("gas_price", GAS_PRICE),
        "chainId": options.get("chain_id", CHAIN_ID),
    }


def erc20_transfer_tx(sender: str, nonce: int, options: dict):
    # data is erc20 transfer function call
    data = "0xa9059cbb" + eth_abi.encode(["address", "uint256"], [sender, 1]).hex()
    return {
        "to": CONTRACT_ADDRESS,
        "value": 0,
        "nonce": nonce,
        "gas": 51630,
        "gasPrice": options.get("gas_price", GAS_PRICE),
        "chainId": options.get("chain_id", CHAIN_ID),
        "data": data,
    }


TX_TYPES = {
    "simple-transfer": simple_transfer_tx,
    "erc20-transfer": erc20_transfer_tx,
}


def build_evm_msg(tx: EthTx):
    return build_any(
        MsgEthereumTx.MSG_URL,
        MsgEthereumTx(
            from_=tx.sender,
            raw=tx.raw,
        ),
    )


def _do_job(job: Job):
    accounts = [gen_account(job.global_seq, i + 1) for i in range(*job.chunk)]
    acct_txs = []
    total = 0
    for acct in accounts:
        txs = []
        for i in range(job.num_txs):
            tx = job.create_tx(acct.address, job.nonce + i, job.tx_options)
            raw = acct.sign_transaction(tx).raw_transaction
            txs.append(EthTx(tx, raw, HexBytes(acct.address)))
            total += 1
            if total % 1000 == 0:
                print(
                    "generated", total, "txs for node", job.global_seq, file=sys.stderr
                )

        # to keep it simple, only build batch inside the account
        txs = [
            build_cosmos_tx(*txs[start:end])
            for start, end in split_batch(len(txs), job.batch)
        ]
        acct_txs.append(txs)
    return acct_txs


def gen(
    global_seq,
    num_accounts,
    num_txs,
    tx_type: str,
    batch: int,
    nonce: int = 0,
    start_account: int = 0,
    tx_options: dict = None,
    evm_denom: str = DEFAULT_DENOM,
) -> [str]:
    tx_options = tx_options or {}
    chunks = split(num_accounts, os.cpu_count())
    create_tx = TX_TYPES[tx_type]
    jobs = [
        Job(
            (start + start_account, end + start_account),
            global_seq,
            num_txs,
            tx_type,
            create_tx,
            batch,
            nonce,
            tx_options,
            evm_denom,
        )
        for start, end in chunks
    ]

    with multiprocessing.Pool() as pool:
        acct_txs = pool.map(_do_job, jobs)

    # mix the account txs together, ordered by nonce.
    all_txs = []
    for txs in itertools.zip_longest(*itertools.chain(*acct_txs)):
        all_txs += txs

    return all_txs


def save(txs: [str], datadir: Path, global_seq: int):
    d = datadir / TXS_DIR
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{global_seq}.json"
    with path.open("w") as f:
        ujson.dump(txs, f)


def load(datadir: Path, global_seq: int) -> [str]:
    path = datadir / TXS_DIR / f"{global_seq}.json"
    if not path.exists():
        return

    with path.open("r") as f:
        return ujson.load(f)


def build_cosmos_tx(*txs: EthTx, denom=DEFAULT_EXTENDED_DENOM) -> str:
    """
    return base64 encoded cosmos tx, support batch
    """
    msgs = [build_evm_msg(tx) for tx in txs]
    fee = sum(tx.tx["gas"] * tx.tx["gasPrice"] for tx in txs)
    gas = sum(tx.tx["gas"] for tx in txs)
    body = TxBody(
        messages=msgs,
        extension_options=[build_any("/cosmos.evm.vm.v1.ExtensionOptionsEthereumTx")],
    )
    auth_info = AuthInfo(
        fee=Fee(
            amount=[Coin(denom=denom, amount=str(fee))],
            gas_limit=gas,
        )
    )
    return base64.b64encode(
        TxRaw(
            body=body.SerializeToString(), auth_info=auth_info.SerializeToString()
        ).SerializeToString()
    ).decode()


def json_rpc_send_body(raw, method="broadcast_tx_async"):
    return {
        "jsonrpc": "2.0",
        "method": method,
        "params": {"tx": raw},
        "id": 1,
    }


@backoff.on_predicate(backoff.expo, max_time=60, max_value=5)
@backoff.on_exception(backoff.expo, aiohttp.ClientError, max_time=60, max_value=5)
async def async_sendtx(session, raw, rpc, sync=False):
    method = "broadcast_tx_sync" if sync else "broadcast_tx_async"
    async with session.post(rpc, json=json_rpc_send_body(raw, method)) as rsp:
        data = await rsp.json()
        if "error" in data:
            print("send tx error, will retry,", data["error"])
            return False
        result = data["result"]
        if result["code"] != 0:
            print("tx is invalid, won't retry,", result["log"])
        return True


async def send(txs, rpc=LOCAL_RPC, sync=False):
    connector = aiohttp.TCPConnector(limit=CONNECTION_POOL_SIZE)
    async with aiohttp.ClientSession(
        connector=connector, json_serialize=ujson.dumps
    ) as session:
        tasks = [
            asyncio.ensure_future(async_sendtx(session, raw, rpc, sync)) for raw in txs
        ]
        await asyncio.gather(*tasks)

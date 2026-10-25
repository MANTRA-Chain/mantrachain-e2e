import asyncio
import json
from decimal import Decimal

import pytest
from eth_contract.utils import sign_transaction

from .network import setup_mantra
from .utils import ACCOUNTS, CHAIN_ID, DEFAULT_DENOM, w3_wait_for_new_blocks_async

pytestmark = pytest.mark.asyncio

# ValidateBasic caps a single tx's declared gas at MaxInt64.
MAX_INT64 = (1 << 63) - 1
# Largest LegacyDec in 1e-18 units (cosmossdk.io/math legacy_dec.go upperLimit).
LEGACY_DEC_MAX = 2**256 * 10**18 - 1


@pytest.fixture(scope="module")
def overflow_mantra(request, tmp_path_factory):
    yield from setup_mantra(request, tmp_path_factory, "feemarket_overflow", 27500)


@pytest.fixture(scope="module")
def recheck_mantra(request, tmp_path_factory):
    yield from setup_mantra(request, tmp_path_factory, "fee_recheck_overflow", 27600)


async def send_max_gas_tx(w3, acct, base_fee, nonce):
    signed = await sign_transaction(
        w3,
        acct,
        to=acct.address,
        value=0,
        gas=MAX_INT64,
        maxFeePerGas=base_fee,
        maxPriorityFeePerGas=0,
        nonce=nonce,
    )
    return await w3.eth.send_raw_transaction(signed.raw_transaction)


async def test_feemarket_gaswanted_overflow_no_halt(overflow_mantra):
    """Two txs whose declared gas sums past MaxInt64 must not halt the chain."""
    w3 = overflow_mantra.async_w3
    acct = ACCOUNTS["community"]

    latest = await w3.eth.get_block("latest")
    base_fee = max(int(latest.get("baseFeePerGas") or 0), 1)

    # fee is reserved up front as gas * maxFeePerGas; the txs execute serially
    # with refunds, so covering a single one at a time is enough
    balance = await w3.eth.get_balance(acct.address)
    assert MAX_INT64 * base_fee <= balance, (MAX_INT64, base_fee, balance)

    # both txs must land in one block to overflow gasWanted; retry if the mempool
    # splits them across blocks
    for _ in range(5):
        nonce = await w3.eth.get_transaction_count(acct.address)
        hashes = [
            await send_max_gas_tx(w3, acct, base_fee, nonce),
            await send_max_gas_tx(w3, acct, base_fee, nonce + 1),
        ]
        receipts = [
            await asyncio.wait_for(w3.eth.wait_for_transaction_receipt(h), timeout=30)
            for h in hashes
        ]
        assert all(r["status"] == 1 for r in receipts), receipts
        if receipts[0]["blockNumber"] == receipts[1]["blockNumber"]:
            break
    else:
        pytest.fail("could not land both MaxInt64-gas txs in the same block")

    # advancing past the overflowing block proves the clamp works — a vulnerable
    # node would have halted in that block's EndBlock
    await asyncio.wait_for(w3_wait_for_new_blocks_async(w3, 3), timeout=60)


async def flood_block(w3, acct, nonce, count=25):
    """Overfill a block with high-tip transfers from `nonce`, raising the base
    fee. Returns the next nonce: evmd's pending nonce ignores queued txs."""
    base_fee = (await w3.eth.get_block("latest"))["baseFeePerGas"]
    for i in range(count):
        signed = await sign_transaction(
            w3,
            acct,
            to=acct.address,
            value=0,
            gas=21000,
            maxFeePerGas=base_fee * 4 + 10,
            maxPriorityFeePerGas=base_fee * 2 + 10,
            nonce=nonce + i,
        )
        await w3.eth.send_raw_transaction(signed.raw_transaction)
    return nonce + count


def node_pids(mantra):
    "The nodes' pids; supervisord restarts a crashed node under a new one."
    nodes = [f"{CHAIN_ID}-node{i}" for i in range(len(mantra.config["validators"]))]
    return mantra.supervisorctl("pid", *nodes).split()


async def test_dynamic_fee_recheck_overflow_no_halt(recheck_mantra, tmp_path):
    """A pending near-max tip cap must not crash nodes on recheck (GHSA-2m6r-q6x4-4w5g).

    The fee checker formed baseFee + tipCap, which overflows LegacyDec once the
    base fee rises after admission, and the async recheck ran it without a
    recover.
    """
    w3 = recheck_mantra.async_w3
    cli = recheck_mantra.cosmos_cli()
    base_fee = Decimal(cli.query_base_fee())

    # baseFee + tipCap sits one unit below the max, so any rise overflows it
    tip_cap = LEGACY_DEC_MAX - int(base_fee.scaleb(18)) - 1
    sender = cli.address("community")
    # a fee cap 5 above the base fee prices the tx below the flood's tip of 10,
    # yet keeps it valid, and overflowing, through the first rises of 1 a block
    unsigned = cli.transfer(
        sender,
        cli.address("signer2"),
        f"1{DEFAULT_DENOM}",
        gas=200000,
        gas_prices=f"{base_fee + 5}{DEFAULT_DENOM}",
        generate_only=True,
    )
    signed = cli.sign_tx_json(
        unsigned,
        sender,
        max_priority_price=f"{tip_cap // 10**18}.{tip_cap % 10**18:018d}",
    )

    # queue the backlog first, so the tx is starved from its first block on
    flood = ACCOUNTS["signer1"]
    nonce = await w3.eth.get_transaction_count(flood.address)
    nonce = await flood_block(w3, flood, nonce, count=50)
    pids = node_pids(recheck_mantra)
    # broadcast_tx_json would wait for an inclusion that must not happen
    tx_file = tmp_path / "tx.json"
    tx_file.write_text(json.dumps(signed))
    rsp = json.loads(
        cli.raw("tx", "broadcast", tx_file, node=cli.node_rpc, output="json")
    )
    assert rsp["code"] == 0, rsp["raw_log"]

    for _ in range(40):
        nonce = await flood_block(w3, flood, nonce)
        await w3_wait_for_new_blocks_async(w3, 1)
        if Decimal(cli.query_base_fee()) > base_fee:
            break
    else:
        pytest.fail("base fee never rose")
    # not included, so it was rechecked at the raised base fee
    assert not cli.tx_search_rpc(f"tx.hash='{rsp['txhash']}'")

    await asyncio.wait_for(w3_wait_for_new_blocks_async(w3, 5), timeout=120)
    # a vulnerable node panics in that recheck
    assert node_pids(recheck_mantra) == pids

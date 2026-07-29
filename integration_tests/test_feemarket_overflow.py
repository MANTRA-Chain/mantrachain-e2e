import asyncio
from pathlib import Path

import pytest
from eth_contract.utils import sign_transaction

from .network import setup_custom_mantra
from .utils import ACCOUNTS, w3_wait_for_new_blocks_async

pytestmark = pytest.mark.asyncio

# ValidateBasic caps a single tx's declared gas at MaxInt64.
MAX_INT64 = (1 << 63) - 1


@pytest.fixture(scope="module")
def overflow_mantra(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp("feemarket_overflow")
    yield from setup_custom_mantra(
        path,
        27500,
        Path(__file__).parent / "configs/feemarket_overflow.jsonnet",
        chain=chain,
    )


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

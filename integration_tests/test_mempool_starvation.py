"""Starved, the node leaves blocks empty while the pool is full and CheckTx
stalls; healthy, the backlog drains at the block gas cap.
"""

import concurrent.futures
import hashlib
import time
from pathlib import Path

import pytest
import requests
from pystarport.utils import wait_for_new_blocks

from . import cosmos_flood
from .cosmos_flood import SignSpec
from .network import setup_custom_mantra
from .utils import eth_to_bech32

pytestmark = pytest.mark.slow

NUM_SENDERS = 2000  # matches the evm-benchmark local profile
TXS_PER_SENDER = 10
TOTAL_TXS = NUM_SENDERS * TXS_PER_SENDER

# per-block capacity = genesis block.max_gas / TX_GAS, must match the jsonnet
TX_GAS = 200_000
BLOCK_CAPACITY = 40_000_000 // TX_GAS  # 200
# the config sets no_base_fee, so any positive gas price clears
GAS_PRICE = 1
FEE = GAS_PRICE * TX_GAS

# fraction of accepted txs the backlog must commit: pre-fix <2%, post-fix ~100%
MIN_COMMITTED_FRACTION = 0.5
FUND_CHUNK = 100


def _priv(i: int) -> bytes:
    return hashlib.sha256(f"flood-{i}".encode()).digest()


def _chain_ctx(cli) -> tuple[str, str, str]:
    """(community, bech32 prefix, bank denom) read from the running chain.

    Not from ADDRESS_PREFIX/EVM_DENOM, which follow scripts/.env and break when
    --chain-config names a different chain (e.g. evmd rejects mantra addresses).
    """
    community = cli.address("community")
    return community, community.split("1", 1)[0], cli.get_params("evm")["evm_denom"]


def _account_meta(cli, addr: str) -> tuple[int, int]:
    """(account_number, sequence), tolerating amino-wrapped vs eth account JSON."""
    val = cli.account(addr)["account"]
    val = val.get("value", val)
    val = val.get("base_account", val)
    return int(val["account_number"]), int(val.get("sequence", 0))


def _block_num_txs(rpc: str, height: int) -> int:
    res = requests.get(f"{rpc}/block_results?height={height}").json()
    assert "result" in res, res
    return len(res["result"].get("txs_results") or [])


def _fund_senders(cli, community, addrs, amount, denom):
    """Fund senders in chunks via bank multi-send, retrying until the balance shows.

    The CLI's exit code is ambiguous: it can't set an explicit sequence online,
    and rebroadcasting identical bytes fails with comet's "tx already seen". A
    unique --note makes each attempt a distinct tx, and one block between
    attempts lets community's sequence advance.
    """

    def funded(addr):
        return int(cli.balance(addr, denom=denom)) >= amount

    for start in range(0, len(addrs), FUND_CHUNK):
        chunk = addrs[start : start + FUND_CHUNK]
        for attempt in range(20):
            if funded(chunk[-1]):
                break
            try:
                cli.raw(
                    "tx",
                    "bank",
                    "multi-send",
                    community,
                    *chunk,
                    f"{amount}{denom}",
                    "-y",
                    gas=8_000_000,
                    gas_prices=f"{GAS_PRICE}{denom}",
                    note=f"fund-{start}-{attempt}",
                    home=cli.data_dir,
                    keyring_backend="test",
                    chain_id=cli.chain_id,
                    node=cli.node_rpc,
                    output="json",
                )
            except AssertionError:
                pass  # ambiguous broadcast, the balance check decides
            wait_for_new_blocks(cli, 1, sleep=0.05)
        assert funded(chunk[-1]), f"funding chunk at {start} never landed"


@pytest.fixture(scope="module")
def mantra_starvation(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp("mantra-mempool-starvation")
    yield from setup_custom_mantra(
        path,
        26500,
        Path(__file__).parent / "configs/mempool_starvation.jsonnet",
        chain=chain,
    )


def test_cosmos_pool_backlog_drains(mantra_starvation):
    cli = mantra_starvation.cosmos_cli(0)
    rpc = cli.node_rpc_http
    community, prefix, denom = _chain_ctx(cli)

    def bech(priv: bytes) -> str:
        return eth_to_bech32(cosmos_flood.address_of(priv), prefix)

    privs = [_priv(i) for i in range(NUM_SENDERS)]
    addrs = [bech(p) for p in privs]
    recipient = bech(_priv(10_000_000))

    _fund_senders(cli, community, addrs, (FEE + 1) * (TXS_PER_SENDER + 2), denom)

    with concurrent.futures.ThreadPoolExecutor(32) as tp:
        metas = list(tp.map(lambda a: _account_meta(cli, a), addrs))

    specs = [
        SignSpec(
            priv=priv,
            from_bech=addr,
            to_bech=recipient,
            amount=1,
            denom=denom,
            gas=TX_GAS,
            fee=FEE,
            seq0=sequence,
            count=TXS_PER_SENDER,
            account_number=account_number,
            chain_id=cli.chain_id,
        )
        for priv, addr, (account_number, sequence) in zip(privs, addrs, metas)
    ]
    with concurrent.futures.ProcessPoolExecutor() as ex:
        chains = list(ex.map(cosmos_flood.sign_chain, specs, chunksize=25))

    # fail fast on a signing bug (probe consumes sender 0's first nonce)
    probe = requests.post(rpc, json=cosmos_flood.broadcast_body(chains[0][0])).json()
    assert probe["result"]["code"] == 0, f"programmatic signing rejected: {probe}"
    chains[0] = chains[0][1:]

    start_height = cli.block_height()
    t0 = time.monotonic()
    results = cosmos_flood.flood(rpc, chains)
    end_height = cli.block_height()

    accepted = sum(1 for code, _ in results if code == 0)
    errors = [(c, log) for c, log in results if c != 0]
    print(
        f"\nflood: accepted={accepted}/{TOTAL_TXS - 1} errors={len(errors)} "
        f"in {time.monotonic() - t0:.1f}s, blocks {start_height}..{end_height}"
    )
    if errors:
        print("sample errors:", errors[:3])
    # insert path must not be fully starved (pre-fix, CheckTx stalls until reset)
    assert (
        accepted >= 10 * BLOCK_CAPACITY
    ), f"only {accepted} txs accepted, {len(errors)} errors — insert path starved"

    # the discriminating check: the backlog must commit. Every tx sends 1 to the
    # same recipient, so its balance counts commits (+1 for the probe)
    deadline = time.time() + 60
    received = cli.balance(recipient, denom=denom)
    while received < accepted and time.time() < deadline:
        wait_for_new_blocks(cli, 1, sleep=0.2)
        received = cli.balance(recipient, denom=denom)

    per_block = {
        h: _block_num_txs(rpc, h) for h in range(start_height + 1, end_height + 1)
    }
    empty = sum(1 for n in per_block.values() if n == 0)
    max_block = max(per_block.values(), default=0)
    print(
        f"committed={received}/{accepted} blocks={len(per_block)} "
        f"empty={empty} max_block={max_block} cap={BLOCK_CAPACITY}"
    )

    frac = received / accepted
    assert frac >= MIN_COMMITTED_FRACTION, (
        f"only {frac:.0%} of the backlog committed with {empty}/{len(per_block)} "
        "empty blocks — proposals starved (reset-to-empty recheck snapshot)"
    )
    # no single block reaps more than the gas cap (Mode 2 guard)
    assert max_block <= BLOCK_CAPACITY, f"oversized block: {max_block}"

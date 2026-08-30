from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest
from pystarport import ports
from pystarport.utils import wait_for_new_blocks, wait_for_port

from .network import setup_custom_mantra
from .utils import (
    ADDRS,
    KEYS,
    modify_command_in_supervisor_config,
    sign_transaction,
)

origin_cmd = None


@pytest.fixture(scope="module")
def custom_mantra(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp("default")
    yield from setup_custom_mantra(
        path,
        27100,
        Path(__file__).parent / "configs/default.jsonnet",
        chain=chain,
    )


def _broadcast(w3s, raw_txs):
    """Send each raw tx to every node in parallel.

    Returns the set of accepted tx hashes. Raises AssertionError naming the
    per-node errors if any tx is rejected by every node — silent swallowing
    would otherwise turn a real mempool failure into a stale-result mystery.
    """
    per_tx_errors = [[] for _ in raw_txs]
    per_tx_hash = [None] * len(raw_txs)

    def submit(idx, w3, raw):
        try:
            return idx, w3.eth.send_raw_transaction(raw), None
        except Exception as e:
            return idx, None, e

    pairs = [(i, w3, raw) for i, raw in enumerate(raw_txs) for w3 in w3s]
    with ThreadPoolExecutor() as exec:
        futures = [exec.submit(submit, i, w3, raw) for i, w3, raw in pairs]
        for f in as_completed(futures):
            idx, h, err = f.result()
            if h is not None:
                per_tx_hash[idx] = h
            else:
                per_tx_errors[idx].append(repr(err))

    for i, h in enumerate(per_tx_hash):
        assert (
            h is not None
        ), f"tx {i} rejected by all {len(w3s)} validators; errors={per_tx_errors[i]}"
    return set(per_tx_hash)


@pytest.mark.unmarked
@pytest.mark.parametrize("max_gas_wanted", [80000000, 40000000, 25000000, 500000, None])
@pytest.mark.skip(reason="https://github.com/cosmos/evm/pull/595")
def test_tx_inclusion(custom_mantra, max_gas_wanted):
    """
    - send multiple heavy transactions at the same time.
    - check they are included in consecutively blocks without failure.
    test against different max-gas-wanted configuration.
    """

    def fn(cmd):
        global origin_cmd
        if origin_cmd is None:
            origin_cmd = cmd
        if max_gas_wanted is None:
            return origin_cmd
        return f"{origin_cmd} --evm.max-tx-gas-wanted {max_gas_wanted}"

    modify_command_in_supervisor_config(
        custom_mantra.base_dir / "tasks.ini",
        lambda cmd: fn(cmd),
        custom_mantra.chain_binary,
    )
    custom_mantra.supervisorctl("update")
    # Wait for every validator's RPC so the broadcast fan-out can land on
    # all of them, not just node 0.
    n_validators = len(custom_mantra.config["validators"])
    for i in range(n_validators):
        wait_for_port(ports.evmrpc_port(custom_mantra.base_port(i)))

    # reset to origin_cmd only
    if max_gas_wanted is None:
        return

    cli = custom_mantra.cosmos_cli()
    # Broadcast to every validator so block-placement assertions don't race
    # gossip latency or the post-restart pool warmup window.
    w3s = [custom_mantra.node_w3(i) for i in range(n_validators)]
    w3 = w3s[0]
    # Read the live block gas limit instead of pinning a literal — keeps the
    # max_tx_in_block math correct if the chain config (default.jsonnet) ever
    # changes its consensus max_gas.
    block_gas_limit = w3.eth.get_block("latest").gasLimit
    tx_gas_limit = 80000000
    max_tx_in_block = block_gas_limit // min(max_gas_wanted, tx_gas_limit)
    print("max_tx_in_block", max_tx_in_block)
    to = ADDRS["validator"]
    tx = {"to": to, "value": 10000, "gas": tx_gas_limit}
    raw_txs = [
        sign_transaction(w3, dict(tx), key).raw_transaction
        for key in list(KEYS.values())[0:4]
    ]
    wait_for_new_blocks(cli, 1, sleep=0.1)
    sended_hash_set = _broadcast(w3s, raw_txs)
    block_nums = [
        w3.eth.wait_for_transaction_receipt(h).blockNumber for h in sended_hash_set
    ]
    block_nums.sort()
    print(f"all block numbers: {block_nums}")
    # the transactions should be included according to max_gas_wanted
    if max_tx_in_block == 1:
        for block_num, next_block_num in zip(block_nums, block_nums[1:]):
            assert next_block_num == block_num + 1 or next_block_num == block_num + 2
    else:
        for num in block_nums[1:max_tx_in_block]:
            assert num == block_nums[0]
        for num in block_nums[max_tx_in_block:]:
            assert num == block_nums[0] + 1 or num == block_nums[0] + 2

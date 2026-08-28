"""Swapping the storage engine under a running chain.

pebble sits two layers below the app hash -- cosmos-db under iavl -- so moving
it from v1 to v2 should be invisible to consensus. node1 comes back on v2 and
has to keep agreeing with node0 and node2, which never load pebble at all.

One binary cannot hold two pebble majors, so both are built: pebble_v1 carries
the format ratchet in cosmos-db and cometbft-db, mantrachaind is what follows.
"""

import functools
import subprocess
from pathlib import Path

import pytest
from pystarport.utils import wait_for_block, wait_for_new_blocks

from .benchmark.utils import block
from .network import setup_custom_mantra
from .utils import (
    derive_new_account,
    fund_acc,
    send_transaction,
    supervisorctl,
    update_node_cmd,
)


@functools.lru_cache(maxsize=2)
def _binary(attr):
    """A mantrachaind from the flake, built on first use."""
    out = subprocess.check_output(
        ["nix", "build", "--no-link", "--print-out-paths", f"..#{attr}"],
        cwd=Path(__file__).parent,
        text=True,
    )
    return f"{out.strip()}/bin/mantrachaind"


PEBBLE_NODE = 1  # the only validator on pebbledb, per configs/default.jsonnet
TRANSFER = 10**16


def _app_hash(cli, height):
    rsp = block(height, rpc=cli.node_rpc_http)
    return rsp["result"]["block"]["header"]["app_hash"]


@pytest.fixture(scope="module")
def mantra_v1(request, tmp_path_factory):
    """A cluster that starts out on pebble v1.

    chain_binary rather than a post_init pass: it reaches `pystarport init`,
    which runs the binary before any hook of ours could redirect it.
    """
    yield from setup_custom_mantra(
        tmp_path_factory.mktemp("pebble_upgrade"),
        27300,
        Path(__file__).parent / "configs/default.jsonnet",
        chain_binary=_binary("mantrachaind-pebble-v1"),
        chain=request.config.getoption("chain_config"),
    )


def test_pebble_v2_keeps_consensus(mantra_v1):
    """A node that swaps pebble v1 for v2 mid-chain must not diverge."""
    mantra = mantra_v1
    w3 = mantra.w3
    # node1's own endpoint, so reads go through the store that changed engine.
    w3_pebble = mantra.node_w3(PEBBLE_NODE)
    cli0 = mantra.cosmos_cli(0)
    cli1 = mantra.cosmos_cli(PEBBLE_NODE)
    proc = f"{mantra.config['chain_id']}-node{PEBBLE_NODE}"
    tasks = mantra.base_dir / "../tasks.ini"

    # State for v2 to inherit. Several transfers rather than one, so the
    # stores hold more than a single version of a single key.
    acct = derive_new_account(600)
    fund_acc(w3, acct)
    first_height = cli1.block_height()
    for _ in range(5):
        receipt = send_transaction(
            w3, {"to": acct.address, "value": TRANSFER, "gasPrice": w3.eth.gas_price}
        )
        assert receipt.status == 1
    wait_for_new_blocks(cli1, 2)

    before = w3_pebble.eth.get_balance(acct.address)
    assert before > 0, "nothing was committed, so the swap would carry nothing"
    swapped_at = cli1.block_height()
    print(f"committed on v1 up to {swapped_at}")

    # The swap. Only node1 moves; node0 and node2 stay on v1 and on goleveldb.
    supervisorctl(tasks, "stop", proc)
    update_node_cmd(mantra.base_dir, _binary("mantrachaind"), PEBBLE_NODE)
    supervisorctl(tasks, "update")
    wait_for_block(cli1, swapped_at + 1)

    # What v1 wrote, v2 reads -- asked of node1 itself.
    assert w3_pebble.eth.get_balance(acct.address) == before

    # Keeping up, not merely surviving the restart.
    wait_for_new_blocks(cli1, 5)

    # Every block from before the swap to after it, against a node that never
    # loaded pebble -- rather than one sampled height.
    last = min(cli0.block_height(), cli1.block_height())
    on_v2 = {h: _app_hash(cli1, h) for h in range(first_height, last + 1)}
    disagreed = [h for h, got in on_v2.items() if got != _app_hash(cli0, h)]
    print(f"compared app hashes {first_height}..{last} across the swap")
    assert not disagreed, (
        f"node1 on pebble v2 and node0 on goleveldb disagree at {disagreed}; "
        f"the swap was at {swapped_at}"
    )
    # The transfers moved state, so the hash has to have moved with it --
    # otherwise the agreement above is agreement about nothing.
    assert len(set(on_v2.values())) > 1, (
        "every height reported the same app hash, so agreeing about them says "
        "nothing about whether the state was read back correctly"
    )

    # New writes land too, so node1 is executing blocks rather than serving
    # what it already had.
    receipt = send_transaction(
        w3, {"to": acct.address, "value": TRANSFER, "gasPrice": w3.eth.gas_price}
    )
    assert receipt.status == 1
    wait_for_new_blocks(cli1, 1)
    assert w3_pebble.eth.get_balance(acct.address) == before + TRANSFER

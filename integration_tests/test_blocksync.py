import time
from pathlib import Path

import pytest
from pystarport import cluster, ports
from pystarport.utils import (
    get_sync_info,
    wait_for_block,
    wait_for_port,
)

from .utils import (
    ADDRS,
    CMD,
    edit_app_cfg,
    send_transaction,
)

CATCHUP_TIMEOUT = 90


def _wait_for_catchup(clustercli, i, target_height):
    """Wait for node i to reach target_height with catching_up=False; fail on stall."""
    deadline = time.time() + CATCHUP_TIMEOUT
    last_height = -1
    last_progress = time.time()
    info = None
    while time.time() < deadline:
        info = get_sync_info(clustercli.status(i))
        h = int(info["latest_block_height"])
        if h > last_height:
            last_height = h
            last_progress = time.time()
        if h >= target_height and not info["catching_up"]:
            return h
        if info["catching_up"] and time.time() - last_progress > 30:
            pytest.fail(
                f"blocksync stalled at height={h} (target={target_height}); "
                f"catching_up={info['catching_up']}"
            )
        time.sleep(1)
    pytest.fail(
        f"blocksync did not finish within {CATCHUP_TIMEOUT}s: "
        f"latest_block_height={last_height}, target={target_height}, "
        f"catching_up={info and info['catching_up']}"
    )


def _spawn_blocksync_node(mantra, moniker, app_config_extra=None, tm_config_extra=None):
    data = Path(mantra.base_dir).parent
    chain_id = mantra.config["chain_id"]
    clustercli = cluster.ClusterCLI(data, cmd=CMD, chain_id=chain_id)
    i = clustercli.create_node(moniker=moniker, statesync=False)
    edit_app_cfg(clustercli, i, app_config_extra or {})

    if tm_config_extra:
        import tomlkit

        path = clustercli.home(i) / "config/config.toml"
        doc = tomlkit.parse(path.read_text())
        for section, kv in tm_config_extra.items():
            doc.setdefault(section, {})
            for k, v in kv.items():
                doc[section][k] = v
        path.write_text(tomlkit.dumps(doc))

    return clustercli, i


def test_blocksync_catchup(mantra):
    """Fresh node joining late must catch up via blocksync (cometbft #5803)."""
    cli0 = mantra.cosmos_cli(0)
    w3 = mantra.w3

    gas_price = w3.eth.gas_price
    for _ in range(3):
        send_transaction(
            w3,
            {"to": ADDRS["signer1"], "value": 1000, "gasPrice": gas_price},
        )
    wait_for_block(cli0, cli0.block_height() + 10)
    join_height = cli0.block_height()

    clustercli, i = _spawn_blocksync_node(mantra, moniker="blocksync")
    proc = f"{clustercli.chain_id}-node{i}"
    clustercli.supervisor.startProcess(proc)
    try:
        caught_height = _wait_for_catchup(clustercli, i, join_height)
        assert caught_height >= join_height

        new_cli = clustercli.cosmos_cli(i)
        wait_for_block(new_cli, caught_height + 3)
        assert not get_sync_info(clustercli.status(i))["catching_up"]

        base_port = ports.evmrpc_port(clustercli.base_port(i))
        wait_for_port(base_port)
    finally:
        clustercli.supervisor.stopProcess(proc)


def test_blocksync_with_pruned_peer(mantra):
    """Catchup against a pruned peer (exercises #5803 base>pool.height path)."""
    cli0 = mantra.cosmos_cli(0)

    wait_for_block(cli0, max(cli0.block_height(), 50))

    join_height = cli0.block_height()
    clustercli, i = _spawn_blocksync_node(
        mantra,
        moniker="blocksync-pruned-peers",
        app_config_extra={
            "pruning": "custom",
            "pruning-keep-recent": "10",
            "pruning-interval": "10",
        },
    )
    proc = f"{clustercli.chain_id}-node{i}"
    clustercli.supervisor.startProcess(proc)
    try:
        caught = _wait_for_catchup(clustercli, i, join_height)
        assert caught >= join_height
        wait_for_block(clustercli.cosmos_cli(i), caught + 3)
        assert not get_sync_info(clustercli.status(i))["catching_up"]
    finally:
        clustercli.supervisor.stopProcess(proc)

import json
import subprocess

import pytest
import tomlkit
from pystarport import ports
from pystarport.utils import wait_for_new_blocks, wait_for_port

from .network import Mantra
from .upgrade_utils import (
    LEGACY_DENOM,
    cleanup_upgrades_folder,
    do_upgrade,
    setup_mantra_upgrade,
)
from .utils import (
    ADDRS,
    CHAIN_ID,
    SCALE_FACTOR,
    AsyncGreeter,
    assert_withdraw_rewards,
    call_with_retry_async,
    update_node_cmd,
    verify_tax_distribution,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.skipped]


@pytest.fixture(scope="module")
def custom_mantra(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    yield from setup_mantra_upgrade(
        tmp_path_factory,
        "upgrade-test-package-recent",
        "cosmovisor_recent",
        "genesis",
        chain=chain,
        port=27010,
    )


async def exec(c):
    cli = c.cosmos_cli()
    w3 = c.async_w3
    grpc_cmd = cli.raw.cmd
    community = ADDRS["community"]
    gas_prices = f"1{LEGACY_DENOM}"
    greeter = AsyncGreeter()
    await greeter.deploy(w3)

    old_height = cli.block_height()
    assert "Hello" == await greeter.greet(block_identifier=old_height)

    balance_bf = await w3.eth.get_balance(community, block_identifier=old_height)
    wait_height = 30

    def cb(cli):
        wait_for_new_blocks(cli, 2)
        stop_height = cli.block_height()
        c.supervisorctl("stop", f"{CHAIN_ID}-node1")
        update_node_cmd(c.base_dir, grpc_cmd, 1, grpc_only=True)
        target_height = stop_height + wait_height
        cli = do_upgrade(c, "v7.0.0-rc4", target_height, denom=LEGACY_DENOM)
        return cli, target_height

    target_height = assert_withdraw_rewards(
        c, cb, denom=LEGACY_DENOM, scale=SCALE_FACTOR, gas_prices=gas_prices
    )
    stop_height = target_height - wait_height

    c.supervisorctl("start", "mantra-canary-net-1-node0")
    wait_for_new_blocks(c.cosmos_cli(), 1)

    verify_tax_distribution(
        cli,
        target_height,
        denom=LEGACY_DENOM,
        scale_factor=SCALE_FACTOR,
    )

    c.supervisorctl("start", "mantra-canary-net-1-node0")
    wait_for_new_blocks(c.cosmos_cli(), 1)

    grpc_node = 1
    api_port = ports.api_port(c.base_port(grpc_node))
    grpc_port = ports.grpc_port(c.base_port(grpc_node))

    def start_grpc_node(logfile):
        return subprocess.Popen(
            [grpc_cmd, "start", "--grpc-only", "--home", c.base_dir / "node1"],
            stdout=logfile,
            stderr=subprocess.STDOUT,
        )

    async def test_historical_queries():
        data = greeter.contract.fns.setGreeting("world").data
        tx = {"to": greeter.address, "from": community, "data": data}
        assert await greeter.greet(block_identifier=old_height) == "Hello"
        assert await w3.eth.estimate_gas(tx, block_identifier=old_height) > 0
        assert (
            await w3.eth.get_balance(community, block_identifier=old_height)
            == balance_bf
        )

    async def query_greeter():
        return await greeter.greet(block_identifier=old_height)

    # run grpc-only mode directly with existing chain state
    with (c.base_dir / "node1.log").open("a") as logfile:
        proc = start_grpc_node(logfile)

        try:
            for port in (grpc_port, api_port):
                wait_for_port(port)

            cli = c.cosmos_cli()
            c.supervisorctl("stop", f"{CHAIN_ID}-node0")
            path = cli.data_dir / "config/app.toml"
            cfg = tomlkit.parse(path.read_text())
            backup_config = json.dumps({f"127.0.0.1:{grpc_port}": [0, stop_height]})
            cfg["grpc"]["historical-grpc-address-block-range"] = backup_config
            path.write_text(tomlkit.dumps(cfg))
            c.supervisorctl("start", f"{CHAIN_ID}-node0")
            wait_for_new_blocks(cli, 1)

            evmrpc_port = ports.evmrpc_port(c.base_port(0))
            wait_for_port(evmrpc_port)

            # test historical contract calls
            test_historical_queries()

            # test restart grpc-only node
            proc.terminate()
            proc.wait(timeout=5)

            assert await call_with_retry_async(query_greeter, expect_error=True)

            balance = await w3.eth.get_balance(community)
            proc = start_grpc_node(logfile)
            for port in (grpc_port, api_port):
                wait_for_port(port)
            wait_for_new_blocks(cli, 1)

            assert await call_with_retry_async(query_greeter, expect_error=False)
            # test historical queries work after reconnection
            await test_historical_queries()
            assert await w3.eth.get_balance(community) == balance
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait()


async def test_cosmovisor_upgrade(custom_mantra: Mantra):
    await exec(custom_mantra)
    cleanup_upgrades_folder(custom_mantra.cosmos_cli().data_dir)

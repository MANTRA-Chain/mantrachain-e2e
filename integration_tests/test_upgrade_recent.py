import json
import subprocess

import pytest
import tomlkit
from pystarport import ports
from pystarport.utils import wait_for_block, wait_for_new_blocks, wait_for_port

from .network import Mantra
from .upgrade_utils import (
    cleanup_upgrades_folder,
    do_upgrade,
    setup_mantra_upgrade,
)
from .utils import ADDRS, CHAIN_ID, Greeter

pytestmark = [pytest.mark.slow, pytest.mark.skipped]


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


def exec(c):
    cli = c.cosmos_cli()
    grpc_cmd = cli.raw.cmd
    w3 = c.w3
    greeter = Greeter("Greeter")
    greeter.deploy(w3)
    old_height = cli.block_height()
    wait_for_new_blocks(cli, 1)

    c.supervisorctl("stop", f"{CHAIN_ID}-node1")

    target_height = cli.block_height() + 15
    cli = do_upgrade(c, "v6.0.0", target_height)

    target_height = cli.block_height() + 15
    cli = do_upgrade(c, "v7.0.0-rc0", target_height)

    grpc_node = 1
    api_port = ports.api_port(c.base_port(grpc_node))
    grpc_port = ports.grpc_port(c.base_port(grpc_node))

    # run grpc-only mode directly with existing chain state
    base_dir = c.base_dir
    with (base_dir / "node1.log").open("a") as logfile:
        proc = subprocess.Popen(
            [
                grpc_cmd,
                "start",
                "--grpc-only",
                "--home",
                base_dir / "node1",
            ],
            stdout=logfile,
            stderr=subprocess.STDOUT,
        )
        try:
            for port in (grpc_port, api_port):
                wait_for_port(port)

            cli = c.cosmos_cli()
            c.supervisorctl("stop", f"{CHAIN_ID}-node0")
            path = cli.data_dir / "config/app.toml"
            cfg = tomlkit.parse(path.read_text())
            backup_config = json.dumps({f"127.0.0.1:{grpc_port}": [0, target_height]})
            cfg["grpc"]["backup-grpc-address-block-range"] = backup_config
            path.write_text(tomlkit.dumps(cfg))
            c.supervisorctl("start", f"{CHAIN_ID}-node0")
            wait_for_block(cli, cli.block_height() + 1)

            evmrpc_port = ports.evmrpc_port(c.base_port(0))
            wait_for_port(evmrpc_port)

            # test historical contract calls
            assert (
                greeter.contract.caller(block_identifier=old_height).greet() == "Hello"
            )
            tx = greeter.contract.functions.setGreeting("world").build_transaction(
                {"from": ADDRS["community"]}
            )
            assert w3.eth.estimate_gas(tx, block_identifier=old_height) > 0
        finally:
            proc.terminate()
            proc.wait()


def test_cosmovisor_upgrade(custom_mantra: Mantra):
    exec(custom_mantra)
    cleanup_upgrades_folder(custom_mantra.cosmos_cli().data_dir)

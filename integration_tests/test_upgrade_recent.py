import subprocess

import pytest
from pystarport import ports
from pystarport.utils import wait_for_new_blocks, wait_for_port

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
    wait_for_new_blocks(cli, 2)

    c.supervisorctl("stop", f"{CHAIN_ID}-node1")

    target_height = cli.block_height() + 15
    cli = do_upgrade(c, "v6.0.0", target_height)

    # run grpc-only mode directly with existing chain state
    base_dir = c.base_dir
    grpc_only_node = 1
    base_port = c.base_port(grpc_only_node)
    grpc_port = ports.grpc_port(base_port)
    api_port = ports.api_port(base_port)
    evmrpc_port = ports.evmrpc_port(base_port)
    with (base_dir / "node1.log").open("a") as logfile:
        proc = subprocess.Popen(
            [
                grpc_cmd,
                "start",
                "--grpc-only",
                "--json-rpc.enable",
                "--home",
                base_dir / "node1",
                "--node",
                cli.node_rpc,
            ],
            stdout=logfile,
            stderr=subprocess.STDOUT,
        )
        try:
            for port in (grpc_port, api_port, evmrpc_port):
                wait_for_port(port)

            target_height = cli.block_height() + 15
            cli = do_upgrade(c, "v7.0.0-rc0", target_height)
            wait_for_new_blocks(cli, 2)

            w3 = c.node_w3(i=1)
            price = w3.eth.gas_price
            assert price > 0
            greeter.w3 = w3
            # test historical contract calls
            assert (
                greeter.contract.caller(block_identifier=old_height).greet() == "Hello"
            )
            tx = greeter.contract.functions.setGreeting("world").build_transaction(
                {"from": ADDRS["community"]}
            )
            gas = w3.eth.estimate_gas(tx, block_identifier=old_height)
            assert gas > 0
        finally:
            proc.terminate()
            proc.wait()


def test_cosmovisor_upgrade(custom_mantra: Mantra):
    exec(custom_mantra)
    cleanup_upgrades_folder(custom_mantra.cosmos_cli().data_dir)

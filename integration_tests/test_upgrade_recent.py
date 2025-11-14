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
    Greeter,
    call_with_retry,
    update_node_cmd,
)

pytest.skip("wait grpc proxy", allow_module_level=True)
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
    w3 = c.w3
    community = ADDRS["community"]
    greeter = Greeter("Greeter")
    greeter.deploy(w3)
    old_height = cli.block_height()

    balance_bf = w3.eth.get_balance(community, block_identifier=old_height)

    wait_for_new_blocks(cli, 1)
    grpc_cmd = cli.raw.cmd
    c.supervisorctl("stop", f"{CHAIN_ID}-node1")
    update_node_cmd(c.base_dir, grpc_cmd, 1, grpc_only=True)

    target_height0 = cli.block_height() + 15
    cli = do_upgrade(c, "v7.0.0-rc0", target_height0, denom=LEGACY_DENOM)

    target_height = cli.block_height() + 15
    cli = do_upgrade(c, "v7.0.0-rc1", target_height, min_deposit=1 * SCALE_FACTOR)

    grpc_node = 1
    api_port = ports.api_port(c.base_port(grpc_node))
    grpc_port = ports.grpc_port(c.base_port(grpc_node))

    def start_grpc_node(logfile):
        return subprocess.Popen(
            [grpc_cmd, "start", "--grpc-only", "--home", c.base_dir / "node1"],
            stdout=logfile,
            stderr=subprocess.STDOUT,
        )

    def test_historical_queries():
        tx = greeter.contract.functions.setGreeting("world").build_transaction(
            {"from": community}
        )
        assert greeter.contract.caller(block_identifier=old_height).greet() == "Hello"
        assert w3.eth.estimate_gas(tx, block_identifier=old_height) > 0
        assert w3.eth.get_balance(community, block_identifier=old_height) == balance_bf

    def query_greeter():
        return greeter.contract.caller(block_identifier=old_height).greet()

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
            backup_config = json.dumps({f"127.0.0.1:{grpc_port}": [0, target_height0]})
            cfg["json-rpc"]["backup-grpc-address-block-range"] = backup_config
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

            assert call_with_retry(query_greeter, expect_error=True)

            balance = w3.eth.get_balance(community)
            proc = start_grpc_node(logfile)
            for port in (grpc_port, api_port):
                wait_for_port(port)
            wait_for_new_blocks(cli, 1)

            assert call_with_retry(query_greeter, expect_error=False)
            # test historical queries work after reconnection
            test_historical_queries()
            assert w3.eth.get_balance(community) == balance
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait()


def test_cosmovisor_upgrade(custom_mantra: Mantra):
    exec(custom_mantra)
    cleanup_upgrades_folder(custom_mantra.cosmos_cli().data_dir)

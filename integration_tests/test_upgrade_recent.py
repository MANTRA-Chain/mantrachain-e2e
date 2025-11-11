import json

import pytest
import tomlkit
import web3
from pystarport import ports
from pystarport.utils import wait_for_block, wait_for_port
from web3 import HTTPProvider

from .network import RETRY_CONFIG, Mantra
from .upgrade_utils import (
    cleanup_upgrades_folder,
    do_upgrade,
    setup_mantra_upgrade,
)
from .utils import CHAIN_ID, CMD, Greeter, supervisorctl, update_node_cmd

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
    )


async def exec(c):
    cli = c.cosmos_cli()
    greeter = Greeter("Greeter")
    greeter.deploy(c.w3)
    old_height = cli.block_height()

    target_height = cli.block_height() + 15
    cli = do_upgrade(c, "v6.0.0", target_height)

    target_height = cli.block_height() + 15
    cli = do_upgrade(c, "v7.0.0-rc0", target_height)

    cli = c.cosmos_cli()
    print("switch to normal binary")
    grpc_node = 2
    update_node_cmd(c.base_dir, CMD, grpc_node)
    supervisorctl(c.base_dir / "../tasks.ini", "update")
    grpc_port = ports.grpc_port(c.base_port(grpc_node))
    wait_for_port(grpc_port)

    c.supervisorctl("stop", f"{CHAIN_ID}-node0")
    path = cli.data_dir / "config/app.toml"
    cfg = tomlkit.parse(path.read_text())
    backup_config = json.dumps({f"127.0.0.1:{grpc_port}": [0, target_height]})
    cfg["json-rpc"]["backup-grpc-address-block-range"] = backup_config
    path.write_text(tomlkit.dumps(cfg))
    c.supervisorctl("start", f"{CHAIN_ID}-node0")
    wait_for_block(cli, cli.block_height() + 1)

    # check query chain state works
    evmrpc_port = ports.evmrpc_port(c.base_port(0))
    wait_for_port(evmrpc_port)
    w3_http_endpoint = f"http://localhost:{evmrpc_port}"
    w3 = web3.Web3(
        HTTPProvider(w3_http_endpoint, exception_retry_configuration=RETRY_CONFIG)
    )
    greeter.w3 = w3
    # test historical contract calls
    assert greeter.contract.caller(block_identifier=old_height).greet() == "Hello"


async def test_cosmovisor_upgrade(custom_mantra: Mantra):
    await exec(custom_mantra)
    cleanup_upgrades_folder(custom_mantra.cosmos_cli().data_dir)

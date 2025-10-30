import time
from pathlib import Path

import pytest
from pystarport import cluster, ports
from web3 import AsyncHTTPProvider, AsyncWeb3

from .network import RETRY_CONFIG, setup_custom_mantra
from .utils import (
    deploy_multi_contracts,
    edit_app_cfg,
    get_sync_info,
    wait_for_block,
    wait_for_port,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def custom_mantra(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp("mix-mempool")
    yield from setup_custom_mantra(
        path,
        27300,
        Path(__file__).parent / "configs/mix_mempool.jsonnet",
        chain=chain,
    )


async def test_mix_async(custom_mantra):
    cli = custom_mantra.cosmos_cli()
    data = Path(custom_mantra.base_dir).parent
    chain_id = custom_mantra.config["chain_id"]
    clustercli = cluster.ClusterCLI(data, cmd="mantrachaind", chain_id=chain_id)
    i = clustercli.create_node(moniker="statesync", statesync=True)
    edit_app_cfg(
        clustercli,
        i,
        app_config={"mempool": {"max-txs": 5000}},
    )
    clustercli.supervisor.startProcess(f"{clustercli.chain_id}-node{i}")
    # Wait 1 more block
    wait_for_block(clustercli.cosmos_cli(i), cli.block_height() + 1)
    time.sleep(1)
    # check query chain state works
    assert not get_sync_info(clustercli.status(i))["catching_up"]
    port = ports.evmrpc_port(clustercli.base_port(i))
    wait_for_port(port)

    w3_http_endpoint = f"http://localhost:{port}"
    w3 = AsyncWeb3(
        AsyncHTTPProvider(
            w3_http_endpoint,
            cache_allowed_requests=True,
            exception_retry_configuration=RETRY_CONFIG,
        ),
    )
    await deploy_multi_contracts(w3, num=1)

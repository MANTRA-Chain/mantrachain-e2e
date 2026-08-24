import socket
from pathlib import Path

import pytest
from pystarport import ports
from pystarport.utils import wait_for_new_blocks

from .network import setup_custom_mantra
from .utils import DEFAULT_DENOM


@pytest.fixture(scope="module")
def mantra_no_evm_mempool(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp("mantra-no-evm-mempool")
    yield from setup_custom_mantra(
        path,
        26340,
        Path(__file__).parent / "configs/evm_mempool_disabled.jsonnet",
        chain=chain,
    )


def test_disabled_evm_mempool(mantra_no_evm_mempool):
    """A node with the EVM mempool disabled runs on the comet flood mempool."""
    c = mantra_no_evm_mempool
    cli = c.cosmos_cli(0)

    community = cli.address("community")
    rsp = cli.transfer(community, cli.address("signer1"), f"1{DEFAULT_DENOM}")
    assert rsp["code"] == 0, rsp["raw_log"]

    # GetMempool returns an untyped nil, so json-rpc refuses to start rather
    # than panicking on the first txpool query
    evmrpc = ports.evmrpc_port(c.base_port(0))
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", evmrpc), timeout=2).close()

    # the node keeps producing blocks afterwards
    wait_for_new_blocks(cli, 2)

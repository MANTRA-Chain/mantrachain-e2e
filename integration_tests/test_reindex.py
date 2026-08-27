from contextlib import contextmanager
from pathlib import Path
from shutil import rmtree

import pytest
import tomlkit
from pystarport import ports
from pystarport.utils import wait_for_new_blocks, wait_for_port
from web3.exceptions import TransactionNotFound, Web3RPCError

from .network import setup_custom_mantra
from .utils import CHAIN_ID, derive_new_account, send_transaction, supervisorctl

pytestmark = pytest.mark.slow

NODE = f"{CHAIN_ID}-node0"
INDEXER_DB = "data/evmindexer.db"


@pytest.fixture(scope="module")
def custom_mantra(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp("reindex")
    yield from setup_custom_mantra(
        path,
        27400,
        Path(__file__).parent / "configs/reindex.jsonnet",
        chain=chain,
    )


@contextmanager
def node_stopped(mantra):
    "stop node0 to unlock its dbs, yield its home, then bring it back"
    ini = mantra.base_dir / "../tasks.ini"
    supervisorctl(ini, "stop", NODE)
    try:
        yield mantra.node_home()
    finally:
        supervisorctl(ini, "start", NODE)
        base_port = mantra.base_port(0)
        wait_for_port(ports.rpc_port(base_port))
        wait_for_port(ports.evmrpc_port(base_port))
        wait_for_new_blocks(mantra.cosmos_cli(), 1)


def set_enable_indexer(home, enabled):
    path = home / "config/app.toml"
    cfg = tomlkit.parse(path.read_text())
    cfg["json-rpc"]["enable-indexer"] = enabled
    path.write_text(tomlkit.dumps(cfg))


def mine_eth_tx(w3):
    receipt = send_transaction(w3, {"to": derive_new_account().address, "value": 1000})
    assert receipt.status == 1
    return receipt.transactionHash, receipt.blockNumber


def assert_indexed(w3, txhash, height):
    assert w3.eth.get_transaction_receipt(txhash).status == 1
    assert w3.eth.get_block(height).transactions == [txhash]


def test_reindex_eth_tx(custom_mantra):
    "a fresh indexer db resumes at the tip, index-eth-tx rebuilds what it skipped"
    w3 = custom_mantra.w3
    txhash, height = mine_eth_tx(w3)
    assert_indexed(w3, txhash, height)

    with node_stopped(custom_mantra) as home:
        rmtree(home / INDEXER_DB)

    with pytest.raises(TransactionNotFound):
        w3.eth.get_transaction_receipt(txhash)
    # one missing entry fails the whole block, not just the one tx
    with pytest.raises(Web3RPCError, match="tx not found"):
        w3.eth.get_block(height)

    with node_stopped(custom_mantra) as home:
        custom_mantra.cosmos_cli().raw("index-eth-tx", "backward", home=home)
    assert_indexed(w3, txhash, height)


def test_comet_index_fallback(custom_mantra):
    "with enable-indexer off the lookup falls back to comet's tx_index"
    w3 = custom_mantra.w3
    txhash, height = mine_eth_tx(w3)

    with node_stopped(custom_mantra) as home:
        rmtree(home / INDEXER_DB)
        set_enable_indexer(home, False)
    try:
        assert_indexed(w3, txhash, height)
    finally:
        with node_stopped(custom_mantra) as home:
            set_enable_indexer(home, True)

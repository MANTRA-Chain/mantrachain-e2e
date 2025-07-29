import time
from pathlib import Path

import pytest
import web3
from pystarport import cluster, ports

from .utils import (
    ADDRS,
    CONTRACTS,
    KEYS,
    Greeter,
    get_sync_info,
    send_transaction,
    wait_for_block,
    wait_for_port,
)


def test_statesync(mantra):
    w3 = mantra.w3
    tx_value = 10000
    gas_price = w3.eth.gas_price
    initial_balance = w3.eth.get_balance(ADDRS["community"])
    tx = {"to": ADDRS["community"], "value": tx_value, "gasPrice": gas_price}
    txhash_0 = send_transaction(w3, tx, KEYS["validator"])["transactionHash"].hex()

    greeter = Greeter(
        CONTRACTS["Greeter"],
        KEYS["validator"],
    )
    txhash_1 = greeter.deploy(w3)["transactionHash"].hex()

    assert w3.eth.get_balance(ADDRS["community"]) == initial_balance + tx_value

    # Wait 5 more block (sometimes not enough blocks can not work)
    cli0 = mantra.cosmos_cli(0)
    wait_for_block(cli0, cli0.block_height() + 5)

    # Check the transactions are added
    assert w3.eth.get_transaction(txhash_0) is not None
    assert w3.eth.get_transaction(txhash_1) is not None

    # add a new state sync node, sync
    # We can not use the mantra fixture to do statesync, since they are full nodes.
    # We can only create a new node with statesync config
    data = Path(mantra.base_dir).parent  # Same data dir as mantra fixture
    chain_id = mantra.config["chain_id"]  # Same chain_id as mantra fixture
    cmd = "mantrachaind"
    # create a clustercli object from ClusterCLI class
    clustercli = cluster.ClusterCLI(data, cmd=cmd, chain_id=chain_id)
    # create a new node with statesync enabled
    i = clustercli.create_node(moniker="statesync", statesync=True)
    # Modify the json-rpc addresses to avoid conflict
    cluster.edit_app_cfg(
        clustercli.home(i) / "config/app.toml",
        clustercli.base_port(i),
        {
            "json-rpc": {
                "enable": True,
                "address": "127.0.0.1:{EVMRPC_PORT}",
                "ws-address": "127.0.0.1:{EVMRPC_PORT_WS}",
            },
        },
    )
    clustercli.supervisor.startProcess(f"{clustercli.chain_id}-node{i}")
    # Wait 1 more block
    wait_for_block(clustercli.cosmos_cli(i), cli0.block_height() + 1)
    time.sleep(2)

    # check query chain state works
    assert not get_sync_info(clustercli.status(i))["catching_up"]

    # check query old transaction doesn't work
    # Get we3 provider
    base_port = ports.evmrpc_port(clustercli.base_port(i))
    print("json-rpc port:", base_port)
    wait_for_port(base_port)
    statesync_w3 = web3.Web3(
        web3.providers.HTTPProvider(f"http://localhost:{base_port}")
    )
    with pytest.raises(web3.exceptions.TransactionNotFound):
        statesync_w3.eth.get_transaction(txhash_0)

    with pytest.raises(web3.exceptions.TransactionNotFound):
        statesync_w3.eth.get_transaction(txhash_1)

    # execute new transactions
    txhash_2 = send_transaction(w3, tx, KEYS["validator"])["transactionHash"].hex()
    txhash_3 = greeter.transfer("world")["transactionHash"].hex()
    # Wait 1 more block
    wait_for_block(clustercli.cosmos_cli(i), cli0.block_height() + 1)

    # check query chain state works
    assert not get_sync_info(clustercli.status(i))["catching_up"]

    # check query new transaction works
    assert statesync_w3.eth.get_transaction(txhash_2) is not None
    assert statesync_w3.eth.get_transaction(txhash_3) is not None
    assert (
        statesync_w3.eth.get_balance(ADDRS["community"])
        == initial_balance + tx_value + tx_value
    )

    print("successfully syncing")
    clustercli.supervisor.stopProcess(f"{clustercli.chain_id}-node{i}")

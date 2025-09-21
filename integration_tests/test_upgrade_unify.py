import json
import re
import subprocess
import time
from pathlib import Path

import pytest
import tomlkit
from eth_contract.erc20 import ERC20
from pystarport import cluster, ports

from .network import Mantra
from .upgrade_utils import (
    cleanup_upgrades_folder,
    do_upgrade,
    patch_app_evm_chain_ids,
    setup_mantra_upgrade,
)
from .utils import (
    DEFAULT_DENOM,
    Greeter,
    assert_create_tokenfactory_denom,
    assert_mint_tokenfactory_denom,
    assert_set_tokenfactory_denom,
    assert_transfer,
    assert_transfer_tokenfactory_denom,
    bech32_to_eth,
    denom_to_erc20_address,
    derive_new_account,
    eth_to_bech32,
    get_sync_info,
    wait_for_block,
    wait_for_new_blocks,
    wait_for_port,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def custom_mantra(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    yield from setup_mantra_upgrade(
        tmp_path_factory,
        "upgrade-test-package",
        "cosmovisor",
        "genesis",
        chain=chain,
    )


async def exec(c, tmp_path):
    cli = c.cosmos_cli()
    community = "community"
    nodes = [f"mantra-canary-net-1-node{i}" for i in range(3)]
    c.supervisorctl("start", *nodes)
    wait_for_new_blocks(cli, 1)

    addr_a = cli.address(community)
    subdenom = f"admin{time.time()}"
    gas_prices = f"1{DEFAULT_DENOM}"
    height = cli.block_height()
    target_height = height + 15

    denom = assert_create_tokenfactory_denom(
        cli, subdenom, is_legacy=True, _from=addr_a, gas_prices=gas_prices
    )
    assert_set_tokenfactory_denom(
        cli, tmp_path, denom, _from=addr_a, gas_prices=gas_prices
    )

    cli = do_upgrade(c, "v5.0", target_height)

    data = Path(c.base_dir).parent
    chain_id = c.config["chain_id"]
    clustercli = cluster.ClusterCLI(data, cmd="mantrachaind", chain_id=chain_id)
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
    wait_for_block(clustercli.cosmos_cli(i), cli.block_height() + 1)
    time.sleep(1)

    # check query chain state works
    assert not get_sync_info(clustercli.status(i))["catching_up"]
    wait_for_port(ports.evmrpc_port(clustercli.base_port(i)))

    print(c.supervisorctl("stop", "all"))
    time.sleep(5)
    patch_app_evm_chain_ids(c)

    config_dir = clustercli.cosmos_cli(i).data_dir / "config"
    patch_chain_id(config_dir)
    patch_genesis(config_dir, "mantra-test-1")

    ini = c.base_dir / "tasks.ini"
    cmd = "command = mantrachaind start --home . --trace --chain-id mantra-canary-net-1"
    ini.write_text(
        re.sub(
            r"^command = mantrachaind start --home .$",
            cmd,
            ini.read_text(),
            flags=re.M,
        )
    )
    c.supervisorctl("update")
    nodes = [f"mantra-canary-net-1-node{i}" for i in range(4)]
    with pytest.raises(subprocess.CalledProcessError):
        c.supervisorctl("start", *nodes)

    patch_genesis(config_dir, "mantra-canary-net-1")
    c.supervisorctl("start", *nodes)
    wait_for_new_blocks(cli, 1)

    # check set contract tx works
    acc_c = derive_new_account(101)
    addr_c = eth_to_bech32(acc_c.address)
    assert_transfer(cli, addr_a, addr_c, amt=10**6)
    greeter = Greeter("Greeter", acc_c.key)
    w3 = c.w3
    greeter.deploy(w3)
    contract = greeter.contract
    assert "Hello" == contract.caller.greet()

    addr_b = cli.create_account("recover")["address"]
    sender = bech32_to_eth(addr_b)
    tf_erc20_addr = denom_to_erc20_address(denom)
    tf_amt = 10**6
    assert_transfer(cli, addr_a, addr_b, amt=tf_amt)

    transfer_amt = 1000
    gas = 300000
    assert_mint_tokenfactory_denom(
        cli, denom, tf_amt, is_legacy=True, _from=community, gas=gas
    )
    assert_transfer_tokenfactory_denom(
        cli, denom, addr_b, transfer_amt, _from=community, gas=gas
    )

    w3 = c.async_w3
    balance = cli.balance(addr_b, denom)
    balance_eth = await ERC20.fns.balanceOf(sender).call(w3, to=tf_erc20_addr)
    total = await ERC20.fns.totalSupply().call(w3, to=tf_erc20_addr)
    assert total == tf_amt
    assert balance == balance_eth == transfer_amt

    transfer_amt2 = 5
    receiver = derive_new_account(4).address
    await ERC20.fns.transfer(receiver, transfer_amt2).transact(
        w3, sender, to=tf_erc20_addr, gasPrice=(await w3.eth.gas_price)
    )

    balance = cli.balance(addr_b, denom)
    balance_eth = await ERC20.fns.balanceOf(sender).call(w3, to=tf_erc20_addr)
    assert balance == balance_eth == transfer_amt - transfer_amt2

    balance = cli.balance(eth_to_bech32(receiver), denom)
    balance_eth = await ERC20.fns.balanceOf(receiver).call(w3, to=tf_erc20_addr)
    assert balance == balance_eth == transfer_amt2

    # check sync node health
    assert abs(clustercli.cosmos_cli(i).block_height() - cli.block_height()) <= 1


async def test_cosmovisor_upgrade(custom_mantra: Mantra, tmp_path):
    await exec(custom_mantra, tmp_path)
    cleanup_upgrades_folder(custom_mantra.cosmos_cli().data_dir)


def patch_chain_id(path):
    cfg_file = path / "app.toml"
    cfg = tomlkit.parse(cfg_file.read_text())
    cfg["evm"] = {}
    cfg_file.write_text(tomlkit.dumps(cfg))


def patch_genesis(path, chain_id):
    genesis_path = path / "genesis.json"
    genesis = json.loads(genesis_path.read_text())
    genesis["chain_id"] = chain_id
    genesis_path.write_text(json.dumps(genesis, indent=2))

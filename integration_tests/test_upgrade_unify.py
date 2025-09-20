import json
import re
import time

import pytest
import tomlkit
from eth_contract.erc20 import ERC20
from pystarport import ports

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

    c.supervisorctl(
        "start",
        "mantra-canary-net-1-node0",
        "mantra-canary-net-1-node1",
        "mantra-canary-net-1-node2",
    )
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

    print(c.supervisorctl("stop", "all"))
    time.sleep(5)
    patch_app_evm_chain_ids(c)
    config_dir = c.cosmos_cli(i=1).data_dir / "config"
    patch_app_toml(config_dir / "app.toml")

    genesis_path = config_dir / "genesis.json"
    genesis = json.loads(genesis_path.read_text())
    genesis["chain_id"] = "mantra-1"
    genesis_path.write_text(json.dumps(genesis, indent=2))

    ini = c.base_dir / "tasks.ini"
    cmd = "command = mantrachaind start --home . --trace --chain-id mantra-canary-net-1"
    ini.write_text(
        re.sub(
            r"^command = cosmovisor run start --home %\(here\)s/node1$",
            cmd,
            ini.read_text(),
            flags=re.M,
        )
    )
    c.supervisorctl("update")

    c.supervisorctl(
        "start",
        "mantra-canary-net-1-node0",
        "mantra-canary-net-1-node1",
        "mantra-canary-net-1-node2",
    )

    wait_for_port(ports.evmrpc_port(c.base_port(0)))

    # check set contract tx works
    acc_c = derive_new_account(101)
    addr_c = eth_to_bech32(acc_c.address)
    assert_transfer(cli, addr_a, addr_c, amt=10**6)
    greeter = Greeter("Greeter", acc_c.key)
    w3 = c.w3
    greeter.deploy(w3)
    contract = greeter.contract
    assert "Hello" == contract.caller.greet()
    wait_for_new_blocks(cli, 2, timeout=20)

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


async def test_cosmovisor_upgrade(custom_mantra: Mantra, tmp_path):
    await exec(custom_mantra, tmp_path)
    cleanup_upgrades_folder(custom_mantra.cosmos_cli().data_dir)


def patch_app_toml(path):
    cfg = tomlkit.parse(path.read_text())
    cfg["evm"] = {}
    path.write_text(tomlkit.dumps(cfg))

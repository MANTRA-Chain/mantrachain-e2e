import time

import pytest
from eth_contract.erc20 import ERC20

from .network import Mantra
from .upgrade_utils import (
    cleanup_upgrades_folder,
    do_upgrade,
    setup_mantra_upgrade,
)
from .utils import (
    assert_create_tokenfactory_denom,
    assert_mint_tokenfactory_denom,
    bech32_to_eth,
    denom_to_erc20_address,
    derive_new_account,
    eth_to_bech32,
    wait_for_new_blocks,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def custom_mantra(tmp_path_factory):
    yield from setup_mantra_upgrade(
        tmp_path_factory, "upgrade-test-package", "cosmovisor_recent", "v5.0.0-rc3"
    )


async def exec(c):
    cli = c.cosmos_cli()
    community = "community"
    gas = 300000

    c.supervisorctl(
        "start",
        "mantra-canary-net-1-node0",
        "mantra-canary-net-1-node1",
        "mantra-canary-net-1-node2",
    )
    wait_for_new_blocks(cli, 1)

    height = cli.block_height()
    target_height = height + 15
    addr_a = cli.address(community)
    signer1 = bech32_to_eth(addr_a)
    subdenom = f"admin{time.time()}"
    denom = assert_create_tokenfactory_denom(
        cli, subdenom, is_legacy=True, _from=addr_a, gas=620000
    )
    tf_erc20_addr = denom_to_erc20_address(denom)
    tf_amt = 10**6
    w3 = c.async_w3
    balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    balance = cli.balance(addr_a, denom)
    balance = assert_mint_tokenfactory_denom(cli, denom, tf_amt, _from=addr_a, gas=gas)
    balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    total = await ERC20.fns.totalSupply().call(w3, to=tf_erc20_addr)
    assert total == balance == balance_eth == tf_amt

    cli = do_upgrade(c, "v5.0.0-rc4", target_height)
    balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    total = await ERC20.fns.totalSupply().call(w3, to=tf_erc20_addr)
    balance = cli.balance(addr_a, denom)
    # miss migrate for dynamic precompiles
    assert total == balance_eth == 0
    assert balance == tf_amt

    height = cli.block_height()
    target_height = height + 15

    cli = do_upgrade(c, "v5.0.0-rc5", target_height)
    balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    total = await ERC20.fns.totalSupply().call(w3, to=tf_erc20_addr)
    balance = cli.balance(addr_a, denom)
    assert total == balance == balance_eth == tf_amt

    receiver = derive_new_account(5).address
    transfer_amt = 5
    await ERC20.fns.transfer(receiver, transfer_amt).transact(
        w3, signer1, to=tf_erc20_addr, gasPrice=(await w3.eth.gas_price)
    )

    balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    balance = cli.balance(addr_a, denom)
    assert balance == balance_eth == total - transfer_amt

    balance_eth = await ERC20.fns.balanceOf(receiver).call(w3, to=tf_erc20_addr)
    balance = cli.balance(eth_to_bech32(receiver), denom)
    assert balance == balance_eth == transfer_amt

    # test approve
    approve_amt = 10
    await ERC20.fns.approve(receiver, approve_amt).transact(
        w3, signer1, to=tf_erc20_addr, gasPrice=(await w3.eth.gas_price)
    )
    allowance = await ERC20.fns.allowance(signer1, receiver).call(w3, to=tf_erc20_addr)
    assert allowance == approve_amt

    # transferFrom signer1 to receiver via receiver with tf_erc20
    signer1_balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    receiver_balance_eth = await ERC20.fns.balanceOf(receiver).call(w3, to=tf_erc20_addr)
    await ERC20.fns.transferFrom(signer1, receiver, approve_amt).transact(
        w3, receiver, to=tf_erc20_addr, gasPrice=(await w3.eth.gas_price)
    )
    balance = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    assert balance == signer1_balance_eth - approve_amt
    balance = await ERC20.fns.balanceOf(receiver).call(w3, to=tf_erc20_addr)
    assert balance == receiver_balance_eth + approve_amt

    c.supervisorctl("stop", "all")
    state = cli.export()["app_state"]
    assert state["erc20"]["native_precompiles"] == [
        "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
    ]


async def test_cosmovisor_upgrade(custom_mantra: Mantra):
    await exec(custom_mantra)
    cleanup_upgrades_folder(custom_mantra.cosmos_cli().data_dir)

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
    DEFAULT_DENOM,
    DEFAULT_EXTENDED_DENOM,
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
)

pytestmark = [pytest.mark.asyncio, pytest.mark.skipped]


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

    # check set contract tx works
    acc_c = derive_new_account(101)
    addr_c = eth_to_bech32(acc_c.address)
    assert_transfer(cli, addr_a, addr_c, amt=10**6)
    greeter = Greeter("Greeter", acc_c.key)
    greeter.deploy(c.w3)
    assert "Hello" == greeter.contract.caller.greet()

    addr_b = cli.create_account("recover")["address"]
    sender = bech32_to_eth(addr_b)
    tf_erc20_addr = denom_to_erc20_address(denom)
    tf_amt = 10**6
    assert_transfer(cli, addr_a, addr_b, amt=tf_amt)

    gas = 300000
    assert_mint_tokenfactory_denom(
        cli, denom, tf_amt, is_legacy=True, _from=community, gas=gas
    )
    assert_transfer_tokenfactory_denom(
        cli, denom, addr_b, 1000, _from=community, gas=gas
    )

    w3 = c.async_w3
    balance = cli.balance(addr_b, denom)
    balance_eth = await ERC20.fns.balanceOf(sender).call(w3, to=tf_erc20_addr)
    total = await ERC20.fns.totalSupply().call(w3, to=tf_erc20_addr)
    assert total == tf_amt
    assert balance == balance_eth == 1000

    transfer_amt = 5
    receiver = derive_new_account(4).address
    sender_balance = 1000
    receiver_balance = 0

    for plan in ["v6.0.0-rc0", "v7.0.0-rc0"]:
        height = cli.block_height()
        target_height = height + 15
        cli = do_upgrade(c, plan, target_height)

        if plan == "v6.0.0-rc0":
            pair = cli.query_erc20_token_pair(denom)
            assert pair["contract_owner"] == "OWNER_MODULE"
            expected = [
                "wasm/cosmos.authz.v1beta1.MsgExec",
                "wasm/cosmos.evm.erc20.v1.MsgRegisterERC20",
            ]
            assert cli.query_disabled_list() == expected
            params = cli.get_params("evm")["params"]
            meta = cli.query_bank_denom_metadata(params["evm_denom"])
            if meta["denom_units"][1]["exponent"] == 6:
                extended_denom = params["extended_denom_options"].get("extended_denom")
                assert extended_denom == DEFAULT_EXTENDED_DENOM

        await ERC20.fns.transfer(receiver, transfer_amt).transact(
            w3, sender, to=tf_erc20_addr, gasPrice=(await w3.eth.gas_price)
        )

        sender_balance -= transfer_amt
        receiver_balance += transfer_amt

        balance = cli.balance(addr_b, denom)
        balance_eth = await ERC20.fns.balanceOf(sender).call(w3, to=tf_erc20_addr)
        assert balance == balance_eth == sender_balance

        balance_receiver = cli.balance(eth_to_bech32(receiver), denom)
        balance_receiver_eth = await ERC20.fns.balanceOf(receiver).call(
            w3, to=tf_erc20_addr
        )
        assert balance_receiver == balance_receiver_eth == receiver_balance


async def test_cosmovisor_upgrade(custom_mantra: Mantra, tmp_path):
    await exec(custom_mantra, tmp_path)
    cleanup_upgrades_folder(custom_mantra.cosmos_cli().data_dir)

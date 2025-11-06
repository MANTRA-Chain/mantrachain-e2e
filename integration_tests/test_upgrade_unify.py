import json
import time

import pytest
from eth_account.signers.base import BaseAccount
from eth_contract.deploy_utils import (
    ensure_create2_deployed,
    ensure_deployed_by_create2,
)
from eth_contract.erc20 import ERC20
from eth_contract.utils import get_initcode, send_transaction
from eth_utils import to_checksum_address
from pystarport.utils import wait_for_new_blocks
from web3 import AsyncWeb3

from .network import Mantra
from .upgrade_utils import (
    LEGACY_DENOM,
    LEGACY_EXTENDED_DENOM,
    cleanup_upgrades_folder,
    do_upgrade,
    setup_mantra_upgrade,
)
from .utils import (
    ACCOUNTS,
    DEFAULT_DENOM,
    WETH_SALT,
    Greeter,
    assert_create_tokenfactory_denom,
    assert_mint_tokenfactory_denom,
    assert_set_tokenfactory_denom,
    assert_transfer,
    assert_transfer_tokenfactory_denom,
    bech32_to_eth,
    build_contract,
    create_periodic_vesting_acct,
    denom_to_erc20_address,
    derive_new_account,
    eth_to_bech32,
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


async def deploy_wom(w3: AsyncWeb3, account: BaseAccount):
    artifact = build_contract("WOM")
    await ensure_create2_deployed(w3, account)
    return await ensure_deployed_by_create2(
        w3,
        account,
        get_initcode(artifact),
        salt=WETH_SALT,
    )


async def exec(c, tmp_path):
    cli = c.cosmos_cli()
    community = "community"
    nodes = [f"mantra-canary-net-1-node{i}" for i in range(3)]
    c.supervisorctl("start", *nodes)
    wait_for_new_blocks(cli, 1)

    addr_a = cli.address(community)
    subdenom = f"admin{time.time()}"
    gas_prices = f"1{LEGACY_DENOM}"

    denom = assert_create_tokenfactory_denom(
        cli, subdenom, is_legacy=True, _from=addr_a, gas_prices=gas_prices
    )
    assert_set_tokenfactory_denom(
        cli, tmp_path, denom, _from=addr_a, gas_prices=gas_prices
    )

    target_height = cli.block_height() + 15
    cli = do_upgrade(c, "v5.0", target_height, denom=LEGACY_DENOM)

    # check set contract tx works
    acc_c = derive_new_account(101)
    addr_c = eth_to_bech32(acc_c.address)
    assert_transfer(
        cli, addr_a, addr_c, amt=10**6, denom=LEGACY_DENOM, gas_prices=gas_prices
    )
    greeter = Greeter("Greeter", acc_c.key)
    greeter.deploy(c.w3)
    assert greeter.contract.caller.greet() == "Hello"

    addr_b = cli.create_account("recover")["address"]
    sender = bech32_to_eth(addr_b)
    tf_erc20_addr = denom_to_erc20_address(denom)
    tf_amt = 10**6
    transfer_amt = 1000
    gas = 300000

    assert_transfer(
        cli, addr_a, addr_b, amt=tf_amt, denom=LEGACY_DENOM, gas_prices=gas_prices
    )
    assert_mint_tokenfactory_denom(
        cli,
        denom,
        tf_amt,
        is_legacy=True,
        _from=community,
        gas=gas,
        gas_prices=gas_prices,
    )
    assert_transfer_tokenfactory_denom(
        cli,
        denom,
        addr_b,
        transfer_amt,
        _from=community,
        gas=gas,
        gas_prices=gas_prices,
    )

    w3 = c.async_w3
    balance = cli.balance(addr_b, denom)
    balance_eth = await ERC20.fns.balanceOf(sender).call(w3, to=tf_erc20_addr)
    total = await ERC20.fns.totalSupply().call(w3, to=tf_erc20_addr)
    assert total == tf_amt and balance == balance_eth == transfer_amt

    transfer_amt2 = 5
    receiver = derive_new_account(4).address
    await ERC20.fns.transfer(receiver, transfer_amt2).transact(
        w3, sender, to=tf_erc20_addr, gasPrice=(await w3.eth.gas_price)
    )

    assert (
        cli.balance(addr_b, denom)
        == await ERC20.fns.balanceOf(sender).call(w3, to=tf_erc20_addr)
        == transfer_amt - transfer_amt2
    )
    assert (
        cli.balance(eth_to_bech32(receiver), denom)
        == await ERC20.fns.balanceOf(receiver).call(w3, to=tf_erc20_addr)
        == transfer_amt2
    )

    old_height = cli.block_height()

    active_precompiles = [
        "0x0000000000000000000000000000000000000800",
        "0x0000000000000000000000000000000000000801",
        "0x0000000000000000000000000000000000000805",
    ]
    target_height = cli.block_height() + 15
    cli = do_upgrade(c, "v6.0.0", target_height, denom=LEGACY_DENOM)
    pair = cli.query_erc20_token_pair(denom)
    assert pair["contract_owner"] == "OWNER_MODULE"
    expected = [
        "wasm/cosmos.authz.v1beta1.MsgExec",
        "wasm/cosmos.evm.erc20.v1.MsgRegisterERC20",
    ]
    assert all(item in cli.query_disabled_list() for item in expected)

    evm_params = cli.get_params("evm")
    meta = cli.query_bank_denom_metadata(evm_params["evm_denom"])
    if meta["denom_units"][1]["exponent"] == 6:
        assert (
            evm_params["extended_denom_options"].get("extended_denom")
            == LEGACY_EXTENDED_DENOM
        )

    await ERC20.fns.transfer(receiver, transfer_amt2).transact(
        w3, sender, to=tf_erc20_addr, gasPrice=(await w3.eth.gas_price)
    )
    assert (
        cli.balance(addr_b, denom)
        == await ERC20.fns.balanceOf(sender).call(w3, to=tf_erc20_addr)
        == transfer_amt - transfer_amt2 * 2
    )
    assert evm_params["active_static_precompiles"] == active_precompiles

    periodic_amt = 1
    coin = f"{periodic_amt}{LEGACY_DENOM}"
    periodic_addr = create_periodic_vesting_acct(
        cli, tmp_path, coin, from_=community, gas_prices=gas_prices
    )

    target_height = cli.block_height() + 15
    cli = do_upgrade(c, "v6.1.0", target_height, denom=LEGACY_DENOM)
    await ERC20.fns.transfer(receiver, transfer_amt2).transact(
        w3, sender, to=tf_erc20_addr, gasPrice=(await w3.eth.gas_price)
    )
    assert (
        cli.balance(addr_b, denom)
        == await ERC20.fns.balanceOf(sender).call(w3, to=tf_erc20_addr)
        == transfer_amt - transfer_amt2 * 3
    )

    deployer = acc_c
    async_w3 = c.async_w3
    wom = await deploy_wom(async_w3, deployer)
    print("wom", wom)
    # deposit
    await send_transaction(async_w3, deployer, to=wom, value=1000)
    # approve
    spender = to_checksum_address(b"\x01" * 20)
    await ERC20.fns.approve(spender, 500).transact(async_w3, deployer, to=wom)

    assert await ERC20.fns.name().call(async_w3, to=wom) == "Wrapped OM"
    assert await ERC20.fns.symbol().call(async_w3, to=wom) == "WOM"
    assert await ERC20.fns.decimals().call(async_w3, to=wom) == 18
    assert await ERC20.fns.balanceOf(deployer.address).call(async_w3, to=wom) == 1000
    assert (
        await ERC20.fns.allowance(deployer.address, spender).call(async_w3, to=wom)
        == 500
    )

    target_height = cli.block_height() + 15
    cli = do_upgrade(c, "v7.0.0-rc0", target_height, denom=LEGACY_DENOM)
    await ERC20.fns.transfer(receiver, transfer_amt2).transact(
        w3, sender, to=tf_erc20_addr, gasPrice=(await w3.eth.gas_price)
    )
    assert (
        cli.balance(addr_b, denom)
        == await ERC20.fns.balanceOf(sender).call(w3, to=tf_erc20_addr)
        == transfer_amt - transfer_amt2 * 4
    )

    # test wom migration
    assert await ERC20.fns.name().call(async_w3, to=wom) == "WMANTRA Token"
    assert await ERC20.fns.symbol().call(async_w3, to=wom) == "WMANTRA"
    assert await ERC20.fns.decimals().call(async_w3, to=wom) == 18
    assert await ERC20.fns.balanceOf(deployer.address).call(async_w3, to=wom) == 4000
    assert (
        await ERC20.fns.allowance(deployer.address, spender).call(async_w3, to=wom)
        == 2000
    )

    # test historical contract calls
    assert greeter.contract.caller(block_identifier=old_height).greet() == "Hello"
    await ERC20.fns.balanceOf(sender).call(
        w3, to=tf_erc20_addr, block_identifier=old_height
    )

    acct = cli.account(periodic_addr)["account"]
    assert acct["type"] == "/cosmos.vesting.v1beta1.PeriodicVestingAccount"
    scale_factor = 4_000_000_000_000
    expected_coin = {"denom": DEFAULT_DENOM, "amount": f"{periodic_amt * scale_factor}"}
    assert acct["value"]["base_vesting_account"]["original_vesting"] == [expected_coin]
    assert acct["value"]["vesting_periods"][0]["amount"] == [expected_coin]

    c.supervisorctl("stop", "all")
    distribution = cli.export(modules_to_export="distribution")["app_state"][
        "distribution"
    ]
    assert "uom" not in json.dumps(distribution)


async def test_cosmovisor_upgrade(custom_mantra: Mantra, tmp_path):
    await exec(custom_mantra, tmp_path)
    cleanup_upgrades_folder(custom_mantra.cosmos_cli().data_dir)

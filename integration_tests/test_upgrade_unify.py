import json
import time

import pytest
import requests
from eth_contract.contract import Contract
from eth_contract.erc20 import ERC20
from eth_contract.utils import send_transaction
from eth_contract.weth import WETH
from eth_utils import to_checksum_address
from pystarport.utils import wait_for_new_blocks

from .network import Mantra
from .upgrade_utils import (
    LEGACY_DENOM,
    LEGACY_EXTENDED_DENOM,
    cleanup_upgrades_folder,
    do_upgrade,
    setup_mantra_upgrade,
)
from .utils import (
    DEFAULT_DENOM,
    SCALE_FACTOR,
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
    deploy_wom,
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


async def exec(c, tmp_path):
    cli = c.cosmos_cli()
    community = "community"

    addr_a = cli.address(community)
    subdenom = f"admin{time.time()}"
    gas_prices = f"1{LEGACY_DENOM}"

    denom = assert_create_tokenfactory_denom(
        cli, subdenom, is_legacy=True, _from=addr_a, gas_prices=gas_prices
    )
    assert_set_tokenfactory_denom(
        cli, tmp_path, denom, _from=addr_a, gas_prices=gas_prices
    )

    res = cli.oracle_query_currency_pairs()
    assert len(res) > 0, res

    wait_height = 30
    target_height = cli.block_height() + wait_height
    cli = do_upgrade(c, "v5.0", target_height, denom=LEGACY_DENOM)

    # check set contract tx works
    acc_c = derive_new_account(101)
    addr_c = eth_to_bech32(acc_c.address)
    delegate_amt = 5_000_000_000_000_000_000
    assert_transfer(
        cli,
        addr_a,
        addr_c,
        amt=10**6 + delegate_amt,
        denom=LEGACY_DENOM,
        gas_prices=gas_prices,
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

    STAKING = "0x0000000000000000000000000000000000000800"
    active_precompiles = [
        STAKING,
        "0x0000000000000000000000000000000000000801",
        "0x0000000000000000000000000000000000000805",
    ]
    target_height = cli.block_height() + wait_height
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

    target_height = cli.block_height() + wait_height
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
    weth = WETH(to=wom)
    await weth.fns.approve(spender, 500).transact(async_w3, deployer, to=wom)

    # before migration
    assert await weth.fns.name().call(async_w3, to=wom) == "Wrapped OM"
    assert await weth.fns.symbol().call(async_w3, to=wom) == "wOM"
    assert await weth.fns.decimals().call(async_w3, to=wom) == 18
    assert await weth.fns.balanceOf(deployer.address).call(async_w3, to=wom) == 1000
    assert (
        await weth.fns.allowance(deployer.address, spender).call(async_w3, to=wom)
        == 500
    )

    # test grant
    granter = cli.address("signer1")
    grantee = cli.address("signer2")
    rsp = cli.grant_fee_allowance(granter, grantee, gas_prices=gas_prices)
    assert rsp["code"] == 0, rsp["raw_log"]

    rsp = cli.revoke_fee_grant(granter, grantee, gas_prices=gas_prices)
    assert rsp["code"] == 0, rsp["raw_log"]

    fee_grant_spend_limit = 5
    rsp = cli.grant_fee_allowance(
        granter,
        grantee,
        spend_limit=f"{fee_grant_spend_limit}{LEGACY_DENOM}",
        gas_prices=gas_prices,
    )
    assert rsp["code"] == 0, rsp["raw_log"]

    def find_grant(auth_type):
        grants = cli.query_grants(granter, grantee)
        return next(
            (g for g in grants if g["authorization"]["type"] == auth_type), None
        )

    # grant_authorization
    max_tokens_limit = 10
    validators = cli.validators()
    val_ops = [v["operator_address"] for v in validators[:2]]
    rsp = cli.grant_authorization(
        grantee,
        "delegate",
        from_=granter,
        spend_limit=f"{max_tokens_limit}{LEGACY_DENOM}",
        allow_list=[val_ops[0]],
        deny_validators=val_ops[1],
        gas_prices=gas_prices,
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    stake_grant = find_grant("/cosmos.staking.v1beta1.StakeAuthorization")
    assert stake_grant and stake_grant["authorization"]["value"]["max_tokens"][
        "amount"
    ] == str(max_tokens_limit)

    spend_limit = 200
    rsp = cli.grant_authorization(
        grantee,
        "send",
        from_=granter,
        spend_limit=f"{spend_limit}{LEGACY_DENOM}",
        gas_prices=gas_prices,
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    send_grant = find_grant("/cosmos.bank.v1beta1.SendAuthorization")
    assert send_grant and send_grant["authorization"]["value"]["spend_limit"][0][
        "amount"
    ] == str(spend_limit)

    # test delegate
    rsp = cli.delegate_amount(
        val_ops[0],
        f"{delegate_amt}{LEGACY_DENOM}",
        _from="signer1",
        gas_prices=gas_prices,
    )
    assert rsp["code"] == 0, rsp["raw_log"]

    target_height_rc2 = cli.block_height() + wait_height
    cli = do_upgrade(c, "v7.0.0", target_height_rc2, denom=LEGACY_DENOM)
    assert cli.get_params("mint")["max_supply"] == str(10_000_000_000 * 10**18)

    # delegate after migration
    PRECOMPILE = Contract(build_contract("StakingI")["abi"])
    DELEGATE = PRECOMPILE.fns.delegate
    res = await DELEGATE(acc_c.address, val_ops[0], delegate_amt).transact(
        async_w3, acc_c, to=STAKING, gas=gas
    )
    assert res.status == 1

    # wom after migration
    await weth.fns.transfer(receiver, transfer_amt2).transact(
        w3, sender, to=tf_erc20_addr, gasPrice=(await w3.eth.gas_price)
    )
    assert (
        cli.balance(addr_b, denom)
        == await weth.fns.balanceOf(sender).call(w3, to=tf_erc20_addr)
        == transfer_amt - transfer_amt2 * 4
    )

    # after migration
    assert await weth.fns.name().call(async_w3, to=wom) == "Wrapped MANTRA"
    assert await weth.fns.symbol().call(async_w3, to=wom) == "wMANTRA"
    assert await weth.fns.decimals().call(async_w3, to=wom) == 18
    assert await weth.fns.balanceOf(deployer.address).call(async_w3, to=wom) == 4000
    assert (
        await weth.fns.allowance(deployer.address, spender).call(async_w3, to=wom)
        == 2000
    )

    # test withdraw
    await weth.fns.withdraw(2000).transact(async_w3, deployer, to=wom)

    # test historical contract calls
    assert greeter.contract.caller(block_identifier=old_height).greet() == "Hello"
    await weth.fns.balanceOf(sender).call(
        w3, to=tf_erc20_addr, block_identifier=old_height
    )

    acct = cli.account(periodic_addr)["account"]
    assert acct["type"] == "/cosmos.vesting.v1beta1.PeriodicVestingAccount"
    expected_coin = {"denom": DEFAULT_DENOM, "amount": f"{periodic_amt * SCALE_FACTOR}"}
    assert acct["value"]["base_vesting_account"]["original_vesting"] == [expected_coin]
    assert acct["value"]["vesting_periods"][0]["amount"] == [expected_coin]

    grant_detail = cli.query_grant(granter, grantee)
    assert grant_detail["allowance"]["value"] == {
        "spend_limit": [
            {
                "denom": DEFAULT_DENOM,
                "amount": str(fee_grant_spend_limit * SCALE_FACTOR),
            }
        ]
    }

    # grant_authorization after migration
    send_grant = find_grant("/cosmos.bank.v1beta1.SendAuthorization")
    assert send_grant and send_grant["authorization"]["value"]["spend_limit"][0][
        "amount"
    ] == str(spend_limit * SCALE_FACTOR)

    def get_block_events():
        rsp = requests.get(
            f"{cli.node_rpc_http}/block_results?height={target_height_rc2}"
        ).json()
        result = rsp.get("result")
        if result is None:
            return []
        return result.get("finalize_block_events") or []

    assert len(get_block_events()) > 0

    c.supervisorctl("stop", "all")
    distribution = cli.export(modules_to_export="distribution")["app_state"][
        "distribution"
    ]
    assert "uom" not in json.dumps(distribution)

    nodes = [f"mantra-canary-net-1-node{i}" for i in range(3)]
    c.supervisorctl("start", *nodes)
    wait_for_new_blocks(cli, 1)

    res = cli.oracle_query_currency_pairs()
    assert len(res) == 0, res

    c.supervisorctl("stop", "all")
    cli.cleanup_block_events(target_height_rc2)
    c.supervisorctl("start", *nodes)
    wait_for_new_blocks(cli, 1)

    assert len(get_block_events()) == 0


async def test_cosmovisor_upgrade(custom_mantra: Mantra, tmp_path):
    await exec(custom_mantra, tmp_path)
    cleanup_upgrades_folder(custom_mantra.cosmos_cli().data_dir)

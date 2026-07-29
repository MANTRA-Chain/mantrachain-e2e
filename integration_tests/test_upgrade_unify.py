import json
import subprocess
import time

import pytest
import requests
import tomlkit
from eth_contract.contract import Contract
from eth_contract.erc20 import ERC20
from eth_contract.weth import WETH
from eth_utils import to_checksum_address
from pystarport import ports
from pystarport.utils import wait_for_new_blocks, wait_for_port

from .network import Mantra
from .upgrade_utils import (
    LEGACY_DENOM,
    cleanup_upgrades_folder,
    do_upgrade,
    setup_mantra_upgrade,
)
from .utils import (
    ADDRS,
    CHAIN_ID,
    DEFAULT_DENOM,
    SCALE_FACTOR,
    AsyncGreeter,
    Greeter,
    assert_create_tokenfactory_denom,
    assert_mint_tokenfactory_denom,
    assert_set_tokenfactory_denom,
    assert_transfer,
    assert_transfer_tokenfactory_denom,
    assert_withdraw_rewards,
    bech32_to_eth,
    build_contract,
    call_with_retry_async,
    create_consumer_chain,
    create_periodic_vesting_acct,
    denom_to_erc20_address,
    deploy_wom,
    derive_new_account,
    eth_to_bech32,
    module_address,
)
from .utils import send_transaction_async as send_transaction
from .utils import (
    update_consumer_chain,
    update_node_cmd,
    verify_tax_distribution,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.skipped]

STAKING = "0x0000000000000000000000000000000000000800"
WAIT_HEIGHT = 30


@pytest.fixture(scope="module")
def custom_mantra(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    yield from setup_mantra_upgrade(
        tmp_path_factory,
        "upgrade-test-package",
        "cosmovisor",
        "genesis",
        chain=chain,
        port=27010,
    )


async def exec(c, tmp_path):
    cli = c.cosmos_cli()
    w3 = c.async_w3
    grpc_cmd = cli.raw.cmd
    community = "community"  # cli key name
    community_addr = ADDRS["community"]  # eth address
    gas_prices = f"1{LEGACY_DENOM}"

    # capture an early height + state for the grpc-only archive checks below
    greeter = AsyncGreeter()
    await greeter.deploy(w3)
    old_height = cli.block_height()
    assert "Hello" == await greeter.greet(block_identifier=old_height)
    balance_bf = await w3.eth.get_balance(community_addr, block_identifier=old_height)

    # pre-v7 state: set up everything the v7 upgrade migrates
    addr_a = cli.address(community)
    subdenom = f"admin{time.time()}"
    gas = 300000
    denom = assert_create_tokenfactory_denom(
        cli, subdenom, is_legacy=True, _from=addr_a, gas=gas, gas_prices=gas_prices
    )
    assert_set_tokenfactory_denom(
        cli, tmp_path, denom, _from=addr_a, gas=gas, gas_prices=gas_prices
    )

    res = cli.oracle_query_currency_pairs()
    assert len(res) > 0, res

    # fund a fresh eth account, deploy a contract and delegate later via it
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
    contract = Greeter("Greeter", acc_c.key)
    contract.deploy(c.w3)
    assert contract.contract.caller.greet() == "Hello"

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

    # historical anchor for pre-v7 contract/erc20 state
    hist_height = cli.block_height()

    # tokenfactory denom auto-registers an erc20 pair owned by the module
    # (v6.1.3 runtime behavior, x/tokenfactory/keeper/createdenom.go)
    pair = cli.query_erc20_token_pair(denom)
    assert pair["contract_owner"] == "OWNER_MODULE"

    # deploy Wrapped OM (wOM); its migration to Wrapped MANTRA is a v7 effect
    deployer = acc_c
    wom = await deploy_wom(w3, deployer)
    print("wom", wom)
    await send_transaction(w3, deployer, to=wom, value=1000)  # deposit
    spender = to_checksum_address(b"\x01" * 20)
    weth = WETH(to=wom)
    await weth.fns.approve(spender, 500).transact(w3, deployer, to=wom)

    # before migration
    assert await weth.fns.name().call(w3, to=wom) == "Wrapped OM"
    assert await weth.fns.symbol().call(w3, to=wom) == "wOM"
    assert await weth.fns.decimals().call(w3, to=wom) == 18
    assert await weth.fns.balanceOf(deployer.address).call(w3, to=wom) == 1000
    assert await weth.fns.allowance(deployer.address, spender).call(w3, to=wom) == 500

    # fee grant + authorization grants (validated for scaling across v7)
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

    rsp = cli.delegate_amount(
        val_ops[0],
        f"{delegate_amt}{LEGACY_DENOM}",
        _from="signer1",
        gas_prices=gas_prices,
    )
    assert rsp["code"] == 0, rsp["raw_log"]

    # periodic vesting account (validated for scaling across v7)
    periodic_amt = 1
    coin = f"{periodic_amt}{LEGACY_DENOM}"
    periodic_addr = create_periodic_vesting_acct(
        cli, tmp_path, coin, from_=community, gas_prices=gas_prices
    )

    # v7.0.0 migration, triggered inside withdraw-rewards flow, cb freezes
    # node2 at pre-v7 state as grpc-only archive node used later
    def cb(cli):
        wait_for_new_blocks(cli, 2)
        stop_height = cli.block_height()
        c.supervisorctl("stop", f"{CHAIN_ID}-node2")
        update_node_cmd(c.base_dir, grpc_cmd, 2, grpc_only=True)
        target_height = stop_height + WAIT_HEIGHT
        cli = do_upgrade(c, "v7.0.0", target_height, denom=LEGACY_DENOM)
        return cli, target_height

    target_height = assert_withdraw_rewards(
        c, cb, denom=LEGACY_DENOM, scale=SCALE_FACTOR, gas_prices=gas_prices
    )
    stop_height = target_height - WAIT_HEIGHT

    c.supervisorctl("start", "mantra-canary-net-1-node0")
    wait_for_new_blocks(c.cosmos_cli(), 1)
    cli = c.cosmos_cli()

    verify_tax_distribution(
        cli,
        target_height,
        denom=LEGACY_DENOM,
        scale_factor=SCALE_FACTOR,
    )

    # post-v7 migration assertions
    assert cli.get_params("mint")["max_supply"] == str(10_000_000_000 * 10**18)

    # delegate via precompile after migration
    staking = Contract(build_contract("StakingI")["abi"])
    res = await staking.fns.delegate(acc_c.address, val_ops[0], delegate_amt).transact(
        w3, acc_c, to=STAKING, gas=gas
    )
    assert res.status == 1

    # tokenfactory erc20 transfer still works after migration
    await ERC20.fns.transfer(receiver, transfer_amt2).transact(
        w3, sender, to=tf_erc20_addr, gasPrice=(await w3.eth.gas_price)
    )
    assert (
        cli.balance(addr_b, denom)
        == await ERC20.fns.balanceOf(sender).call(w3, to=tf_erc20_addr)
        == transfer_amt - transfer_amt2 * 2
    )

    # wom migrated to Wrapped MANTRA (4x scale is a v7 migration effect)
    assert await weth.fns.name().call(w3, to=wom) == "Wrapped MANTRA"
    assert await weth.fns.symbol().call(w3, to=wom) == "wMANTRA"
    assert await weth.fns.decimals().call(w3, to=wom) == 18
    assert await weth.fns.balanceOf(deployer.address).call(w3, to=wom) == 4000
    assert await weth.fns.allowance(deployer.address, spender).call(w3, to=wom) == 2000
    await weth.fns.withdraw(2000).transact(w3, deployer, to=wom)

    # historical contract/erc20 calls against pre-v7 state
    assert contract.contract.caller(block_identifier=hist_height).greet() == "Hello"
    await ERC20.fns.balanceOf(sender).call(
        w3, to=tf_erc20_addr, block_identifier=hist_height
    )

    # periodic vesting scaled
    acct = cli.account(periodic_addr)["account"]
    assert acct["type"] == "/cosmos.vesting.v1beta1.PeriodicVestingAccount"
    expected_coin = {"denom": DEFAULT_DENOM, "amount": f"{periodic_amt * SCALE_FACTOR}"}
    assert acct["value"]["base_vesting_account"]["original_vesting"] == [expected_coin]
    assert acct["value"]["vesting_periods"][0]["amount"] == [expected_coin]

    # fee grant scaled
    grant_detail = cli.query_grant(granter, grantee)
    assert grant_detail["allowance"]["value"] == {
        "spend_limit": [
            {
                "denom": DEFAULT_DENOM,
                "amount": str(fee_grant_spend_limit * SCALE_FACTOR),
            }
        ]
    }

    # send authorization scaled
    send_grant = find_grant("/cosmos.bank.v1beta1.SendAuthorization")
    assert send_grant and send_grant["authorization"]["value"]["spend_limit"][0][
        "amount"
    ] == str(spend_limit * SCALE_FACTOR)

    # block events / distribution export / oracle removal
    def get_block_events():
        rsp = requests.get(
            f"{cli.node_rpc_http}/block_results?height={target_height}"
        ).json()
        result = rsp.get("result")
        if result is None:
            return []
        return result.get("finalize_block_events") or []

    assert len(get_block_events()) > 0

    # node2 is frozen as the grpc-only archive node, so only restart the
    # two validators for the offline-export / block-events checks.
    nodes = [f"{CHAIN_ID}-node{i}" for i in range(2)]
    c.supervisorctl("stop", "all")
    distribution = cli.export(modules_to_export="distribution")["app_state"][
        "distribution"
    ]
    assert "uom" not in json.dumps(distribution)

    c.supervisorctl("start", *nodes)
    wait_for_new_blocks(cli, 1)

    res = cli.oracle_query_currency_pairs()
    assert len(res) == 0, res

    c.supervisorctl("stop", "all")
    cli.cleanup_block_events(target_height)
    c.supervisorctl("start", *nodes)
    wait_for_new_blocks(cli, 1)
    assert len(get_block_events()) == 0

    # remaining upgrades v8.0.0 -> v8.3.0
    cli = do_upgrade(c, "v8.0.0", cli.block_height() + WAIT_HEIGHT, scale=SCALE_FACTOR)
    cli = do_upgrade(c, "v8.1.1", cli.block_height() + WAIT_HEIGHT, scale=SCALE_FACTOR)
    cli = do_upgrade(c, "v8.2.0", cli.block_height() + WAIT_HEIGHT, scale=SCALE_FACTOR)
    cli = do_upgrade(c, "v8.3.0", cli.block_height() + WAIT_HEIGHT, scale=SCALE_FACTOR)

    verify_removed_modules(cli)
    await verify_provider(cli)

    # grpc-only historical queries via the frozen node2 archive (backend for node0)
    grpc_node = 2
    api_port = ports.api_port(c.base_port(grpc_node))
    grpc_port = ports.grpc_port(c.base_port(grpc_node))

    def start_grpc_node(logfile):
        return subprocess.Popen(
            [
                grpc_cmd,
                "start",
                "--grpc-only",
                "--home",
                c.base_dir / f"node{grpc_node}",
            ],
            stdout=logfile,
            stderr=subprocess.STDOUT,
        )

    async def test_historical_queries():
        data = greeter.contract.fns.setGreeting("world").data
        tx = {"to": greeter.address, "from": community_addr, "data": data}
        assert await greeter.greet(block_identifier=old_height) == "Hello"
        assert await w3.eth.estimate_gas(tx, block_identifier=old_height) > 0
        assert (
            await w3.eth.get_balance(community_addr, block_identifier=old_height)
            == balance_bf
        )

    async def query_greeter():
        return await greeter.greet(block_identifier=old_height)

    with (c.base_dir / f"node{grpc_node}.log").open("a") as logfile:
        proc = start_grpc_node(logfile)

        try:
            for port in (grpc_port, api_port):
                wait_for_port(port)

            cli = c.cosmos_cli()
            c.supervisorctl("stop", f"{CHAIN_ID}-node0")
            path = cli.data_dir / "config/app.toml"
            cfg = tomlkit.parse(path.read_text())
            backup_config = json.dumps({f"127.0.0.1:{grpc_port}": [0, stop_height]})
            cfg["grpc"]["historical-grpc-address-block-range"] = backup_config
            path.write_text(tomlkit.dumps(cfg))
            c.supervisorctl("start", f"{CHAIN_ID}-node0")
            wait_for_new_blocks(cli, 1)

            evmrpc_port = ports.evmrpc_port(c.base_port(0))
            wait_for_port(evmrpc_port)

            await test_historical_queries()

            # restart the grpc-only node
            proc.terminate()
            proc.wait(timeout=5)
            assert await call_with_retry_async(query_greeter, expect_error=True)

            balance = await w3.eth.get_balance(community_addr)
            proc = start_grpc_node(logfile)
            for port in (grpc_port, api_port):
                wait_for_port(port)
            wait_for_new_blocks(cli, 1)

            assert await call_with_retry_async(query_greeter, expect_error=False)
            await test_historical_queries()
            assert await w3.eth.get_balance(community_addr) == balance
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait()


async def verify_provider(cli):
    params = cli.get_params("provider")
    assert params["blocks_per_epoch"] == "10"
    assert params["number_of_epochs_to_start_receiving_rewards"] == "2"
    fee = params.get("consumer_reward_denom_registration_fee")
    assert fee == {"denom": DEFAULT_DENOM, "amount": "4000000000000000000"}
    assert int(params.get("max_provider_consensus_validators")) > 0
    consumer_id = create_consumer_chain(cli, "test-consumer-1", from_="validator")
    rsp = cli.provider_opt_in(consumer_id, from_="validator")
    assert rsp["code"] == 0, rsp["raw_log"]

    authority = module_address("gov")
    owner_address = cli.address("validator")
    update_consumer_chain(
        cli,
        consumer_id,
        cli.data_dir.parent,
        owner_address,
        authority,
        from_="validator",
    )

    wait_for_new_blocks(cli, 1)
    assert cli.provider_consumer_genesis(consumer_id) is not None


def verify_removed_modules(cli):
    assert not cli.has_module("oracle")
    assert not cli.has_module("marketmap")

    with pytest.raises(AssertionError):
        cli.get_params("oracle")

    with pytest.raises(AssertionError):
        cli.get_params("marketmap")


async def test_cosmovisor_upgrade(custom_mantra: Mantra, tmp_path):
    await exec(custom_mantra, tmp_path)
    cleanup_upgrades_folder(custom_mantra.cosmos_cli().data_dir)

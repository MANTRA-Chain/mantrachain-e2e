import json
import subprocess
import time

import pytest
import requests
import tomlkit
from eth_contract.contract import Contract
from eth_contract.erc20 import ERC20
from pystarport import ports
from pystarport.utils import wait_for_new_blocks, wait_for_port

from .network import Mantra
from .upgrade_utils import (
    cleanup_upgrades_folder,
    do_upgrade,
    setup_mantra_upgrade,
)
from .utils import (
    ADDRS,
    CHAIN_ID,
    DEFAULT_DENOM,
    DEFAULT_GAS_PRICE,
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
    derive_new_account,
    ensure_comet_mempool_app,
    eth_to_bech32,
    module_address,
    update_consumer_chain,
    update_node_cmd,
    verify_tax_distribution,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.skipped]

STAKING = "0x0000000000000000000000000000000000000800"
WAIT_HEIGHT = 16


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


async def run_upgrades(c, tmp_path):
    cli = c.cosmos_cli()
    w3 = c.async_w3
    grpc_cmd = cli.raw.cmd
    community = "community"  # cli key name
    community_addr = ADDRS["community"]  # eth address
    gas_prices = DEFAULT_GAS_PRICE

    # capture an early height + state for the grpc-only archive checks below
    greeter = AsyncGreeter()
    await greeter.deploy(w3)
    old_height = cli.block_height()
    assert "Hello" == await greeter.greet(block_identifier=old_height)
    balance_bf = await w3.eth.get_balance(community_addr, block_identifier=old_height)

    # pre-v8 state: everything below has to survive the v8.x upgrade chain
    addr_a = cli.address(community)
    subdenom = f"admin{time.time()}"
    gas = 300000
    # the genesis binary pairs an erc20 with the denom, so these write through to
    # the contract too; a mint alone measures ~305k, well over the plain 300k
    tf_gas = 620000
    denom = assert_create_tokenfactory_denom(
        cli, subdenom, _from=addr_a, gas=tf_gas, gas_prices=gas_prices
    )
    assert_set_tokenfactory_denom(
        cli, tmp_path, denom, _from=addr_a, gas=tf_gas, gas_prices=gas_prices
    )

    # fund a fresh eth account, deploy a contract and delegate later via it
    acc_c = derive_new_account(101)
    addr_c = eth_to_bech32(acc_c.address)
    delegate_amt = 5_000_000_000_000_000_000
    assert_transfer(
        cli,
        addr_a,
        addr_c,
        amt=10**18 + delegate_amt,
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

    # addr_b sends the erc20 tx below, so fund it for gas rather than with tf_amt
    assert_transfer(cli, addr_a, addr_b, amt=10**18, gas_prices=gas_prices)
    assert_mint_tokenfactory_denom(
        cli, denom, tf_amt, _from=addr_a, gas=tf_gas, gas_prices=gas_prices
    )
    assert_transfer_tokenfactory_denom(
        cli,
        denom,
        addr_b,
        transfer_amt,
        _from=addr_a,
        gas=tf_gas,
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

    # historical anchor for pre-v8 contract/erc20 state
    hist_height = cli.block_height()

    # fee grant + authorization grants, checked again after the upgrades
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
        spend_limit=f"{fee_grant_spend_limit}{DEFAULT_DENOM}",
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
        spend_limit=f"{max_tokens_limit}{DEFAULT_DENOM}",
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
        spend_limit=f"{spend_limit}{DEFAULT_DENOM}",
        gas_prices=gas_prices,
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    send_grant = find_grant("/cosmos.bank.v1beta1.SendAuthorization")
    assert send_grant and send_grant["authorization"]["value"]["spend_limit"][0][
        "amount"
    ] == str(spend_limit)

    rsp = cli.delegate_amount(
        val_ops[0],
        f"{delegate_amt}{DEFAULT_DENOM}",
        _from="signer1",
        gas_prices=gas_prices,
    )
    assert rsp["code"] == 0, rsp["raw_log"]

    periodic_amt = 1
    coin = f"{periodic_amt}{DEFAULT_DENOM}"
    periodic_addr = create_periodic_vesting_acct(
        cli, tmp_path, coin, from_=community, gas_prices=gas_prices
    )

    # first upgrade, triggered inside withdraw-rewards flow, cb freezes node2 at
    # its pre-upgrade state as the grpc-only archive node used later
    def cb(cli):
        wait_for_new_blocks(cli, 2)
        stop_height = cli.block_height()
        c.supervisorctl("stop", f"{CHAIN_ID}-node2")
        update_node_cmd(c.base_dir, grpc_cmd, 2, grpc_only=True)
        target_height = stop_height + WAIT_HEIGHT
        cli = do_upgrade(c, "v8.4.0", target_height)
        return cli, target_height

    # validator self-delegation needs more than the cli's 200k default
    target_height = assert_withdraw_rewards(c, cb, gas=gas, gas_prices=gas_prices)
    stop_height = target_height - WAIT_HEIGHT

    c.supervisorctl("start", "mantra-canary-net-1-node0")
    wait_for_new_blocks(c.cosmos_cli(), 1)
    cli = c.cosmos_cli()

    verify_tax_distribution(cli, target_height)

    # delegate via precompile after the upgrade
    staking = Contract(build_contract("StakingI")["abi"])
    res = await staking.fns.delegate(acc_c.address, val_ops[0], delegate_amt).transact(
        w3, acc_c, to=STAKING, gas=gas
    )
    assert res.status == 1

    # tokenfactory erc20 transfer still works after the upgrade
    await ERC20.fns.transfer(receiver, transfer_amt2).transact(
        w3, sender, to=tf_erc20_addr, gasPrice=(await w3.eth.gas_price)
    )
    assert (
        cli.balance(addr_b, denom)
        == await ERC20.fns.balanceOf(sender).call(w3, to=tf_erc20_addr)
        == transfer_amt - transfer_amt2 * 2
    )

    # historical contract/erc20 calls against pre-v8 state
    assert contract.contract.caller(block_identifier=hist_height).greet() == "Hello"
    await ERC20.fns.balanceOf(sender).call(
        w3, to=tf_erc20_addr, block_identifier=hist_height
    )

    # periodic vesting, fee grant and send authorization survive the upgrade
    acct = cli.account(periodic_addr)["account"]
    assert acct["type"] == "/cosmos.vesting.v1beta1.PeriodicVestingAccount"
    expected_coin = {"denom": DEFAULT_DENOM, "amount": f"{periodic_amt}"}
    assert acct["value"]["base_vesting_account"]["original_vesting"] == [expected_coin]
    assert acct["value"]["vesting_periods"][0]["amount"] == [expected_coin]

    grant_detail = cli.query_grant(granter, grantee)
    assert grant_detail["allowance"]["value"] == {
        "spend_limit": [
            {
                "denom": DEFAULT_DENOM,
                "amount": str(fee_grant_spend_limit),
            }
        ]
    }

    send_grant = find_grant("/cosmos.bank.v1beta1.SendAuthorization")
    assert send_grant and send_grant["authorization"]["value"]["spend_limit"][0][
        "amount"
    ] == str(spend_limit)

    # block events survive the upgrade and can be pruned afterwards
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
    # two validators for the block-events check.
    nodes = [f"{CHAIN_ID}-node{i}" for i in range(2)]
    c.supervisorctl("stop", "all")
    cli.cleanup_block_events(target_height)
    c.supervisorctl("start", *nodes)
    wait_for_new_blocks(cli, 1)
    assert len(get_block_events()) == 0

    # final upgrade, onto the first cometbft v0.39 binary
    ensure_comet_mempool_app(c.base_dir)
    cli = do_upgrade(c, "v8.5.0", cli.block_height() + WAIT_HEIGHT)

    verify_removed_modules(cli)
    blacklist = cli.query_blacklist()
    V8_4_EXPLOITER = "mantra13n9sk3p8x7tpq9adgxvzv9q0qev953mld0hwva"
    assert V8_4_EXPLOITER in blacklist, f"blacklist fail in v8.4.0: {blacklist}"
    verify_v8_4_vesting_disabled(cli)
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


def verify_v8_4_vesting_disabled(cli):
    to_addr = cli.create_account(f"vesting_blocked{int(time.time())}")["address"]
    try:
        rsp = json.loads(
            cli.raw(
                "tx",
                "vesting",
                "create-permanent-locked-account",
                to_addr,
                f"1{DEFAULT_DENOM}",
                "-y",
                **(cli.get_kwargs_with_gas() | {"from": "community"}),
            )
        )
    except Exception as e:  # CLI may exit non-zero when the ante rejects the tx
        assert "tx type not allowed" in str(e), e
        return
    assert rsp.get("code", 0) != 0, f"vesting creation was not circuit-broken: {rsp}"
    assert "tx type not allowed" in rsp.get("raw_log", ""), rsp


def verify_removed_modules(cli):
    assert not cli.has_module("oracle")
    assert not cli.has_module("marketmap")

    with pytest.raises(AssertionError):
        cli.get_params("oracle")

    with pytest.raises(AssertionError):
        cli.get_params("marketmap")


async def test_cosmovisor_upgrade(custom_mantra: Mantra, tmp_path):
    await run_upgrades(custom_mantra, tmp_path)
    cleanup_upgrades_folder(custom_mantra.cosmos_cli().data_dir)

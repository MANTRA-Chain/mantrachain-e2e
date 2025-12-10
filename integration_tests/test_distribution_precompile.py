import pytest
import requests
from eth_contract.contract import Contract
from pystarport.utils import parse_amount, wait_for_block, wait_for_new_blocks

from .utils import (
    ACCOUNTS,
    DEFAULT_DENOM,
    WEI_PER_DENOM,
    bech32_to_eth,
    build_contract,
    eth_to_bech32,
    find_fee,
    find_log_event_attrs,
    w3_wait_for_new_blocks_async,
)

pytestmark = pytest.mark.asyncio

PRECOMPILE = Contract(build_contract("DistributionI")["abi"])

DISTRIBUTION = "0x0000000000000000000000000000000000000801"

gas = 400_000


async def community_pool(w3):
    res = await PRECOMPILE.fns.communityPool().call(w3, to=DISTRIBUTION)
    return res[0][1] if res else 0


async def get_rewards(w3, delegator, val_addr, block=None):
    res = await PRECOMPILE.fns.delegationRewards(delegator, val_addr).call(
        w3, to=DISTRIBUTION, block_identifier=block
    )
    return res[0][1] if res else 0


@pytest.mark.connect
async def test_connect_distribution(connect_mantra, tmp_path):
    await test_distribution(None, connect_mantra, tmp_path)


async def test_distribution(mantra, connect_mantra, tmp_path):
    cli = connect_mantra.cosmos_cli(tmp_path)
    tax = cli.get_params("distribution")["community_tax"]
    if float(tax) < 0.01:
        pytest.skip(f"community_tax is {tax} too low for test")
    w3 = connect_mantra.async_w3
    signer1, signer2 = cli.address("signer1"), cli.address("signer2")

    wait_for_block(cli, 2)

    balance_bf = cli.balance(signer1)
    community_bf = await community_pool(w3)

    amt = 2
    rsp = cli.transfer(signer1, signer2, f"{amt}{DEFAULT_DENOM}")
    assert rsp["code"] == 0, rsp["raw_log"]

    fee = find_fee(rsp)
    wait_for_new_blocks(cli, 2)

    assert cli.balance(signer1) == balance_bf - fee - amt
    assert await community_pool(w3) > community_bf


@pytest.mark.connect
async def test_connect_withdraw_rewards(connect_mantra, tmp_path):
    await test_withdraw_rewards(None, connect_mantra, tmp_path)


async def test_withdraw_rewards(mantra, connect_mantra, tmp_path):
    cli = connect_mantra.cosmos_cli(tmp_path)
    w3 = connect_mantra.async_w3
    acct = ACCOUNTS["signer1"]
    val = cli.address("validator", "val")
    validator = cli.debug_addr(val, bech="hex")
    signer1 = cli.address("signer1")
    signer2 = cli.address("signer2")
    signer1_eth = bech32_to_eth(signer1)
    signer2_eth = bech32_to_eth(signer2)
    delegate_amt = 20_000_000
    gas0 = 250_000
    coin = f"{delegate_amt}{DEFAULT_DENOM}"

    res = await PRECOMPILE.fns.setWithdrawAddress(acct.address, signer2).transact(
        w3, acct, to=DISTRIBUTION, gas=gas
    )
    assert res.status == 1

    rsp = cli.delegate_amount(val, coin, _from=signer1, gas=gas0)
    assert rsp["code"] == 0, rsp["raw_log"]
    rsp = cli.delegate_amount(val, coin, _from=eth_to_bech32(validator), gas=gas0)
    assert rsp["code"] == 0, rsp["raw_log"]

    await w3_wait_for_new_blocks_async(w3, 3)
    block = await w3.eth.block_number

    rewards = [
        await get_rewards(w3, signer1_eth, val, block=block - 1),
        await get_rewards(w3, signer1_eth, val, block=block),
    ]
    diff = rewards[1] / rewards[0]
    assert diff >= 1 and diff <= 2, "rewards should increase"

    # TODO: check after query get merged
    # period = cli.query_delegator_starting_info(signer1, val)["previous_period"]
    # start = parse_amount(
    #     cli.query_validator_historical_rewards(val, period).get(
    #         "cumulative_reward_ratio", [{}]
    #     )[0]
    # )

    res = await PRECOMPILE.fns.withdrawDelegatorRewards(acct.address, val).transact(
        w3, acct, to=DISTRIBUTION, gas=gas
    )
    assert res.status == 1
    height = res["blockNumber"]
    # info = cli.query_delegator_starting_info(signer1, val, height=height)
    # stake = float(info["stake"])
    # period = info["previous_period"]
    # end = parse_amount(
    #     cli.query_validator_historical_rewards(val, period, height=height).get(
    #         "cumulative_reward_ratio", [{}]
    #     )[0]
    # )
    balances = [
        await w3.eth.get_balance(signer2_eth, block_identifier=height - 1),
        await w3.eth.get_balance(signer2_eth, block_identifier=height),
    ]
    print("mm-balances:", int(balances[1] - balances[0]))
    assert int(balances[1] - balances[0]) > 0
    # assert int(stake * (end - start)) == int(balances[1] - balances[0])


@pytest.mark.connect
async def test_connect_community_pool_funding(connect_mantra):
    await test_community_pool_funding(None, connect_mantra)


async def test_community_pool_funding(mantra, connect_mantra):
    w3 = connect_mantra.async_w3
    acct = ACCOUNTS["signer1"]
    initial_pool = await community_pool(w3)
    fund_amount = 1000
    balance_bf = await w3.eth.get_balance(acct.address)

    coin = [[DEFAULT_DENOM, fund_amount]]
    res = await PRECOMPILE.fns.fundCommunityPool(acct.address, coin).transact(
        w3, acct, to=DISTRIBUTION, gas=gas
    )
    assert res.status == 1

    balance_af = await w3.eth.get_balance(acct.address)
    fee = res["gasUsed"] * res["effectiveGasPrice"]
    assert (
        balance_af == balance_bf - fund_amount * WEI_PER_DENOM - fee
    ), "balance should decrease"

    final_pool = await community_pool(w3)
    assert final_pool >= initial_pool + fund_amount, "community pool should increase"


@pytest.mark.connect
async def test_connect_validator_rewards_pool_funding(connect_mantra, tmp_path):
    await test_validator_rewards_pool_funding(None, connect_mantra, tmp_path)


async def test_validator_rewards_pool_funding(mantra, connect_mantra, tmp_path):
    cli = connect_mantra.cosmos_cli(tmp_path)
    w3 = connect_mantra.async_w3
    acct = ACCOUNTS["signer1"]
    val = cli.validators()[0]["operator_address"]
    fund_amount = 1000
    coin = [[DEFAULT_DENOM, fund_amount]]
    res = await PRECOMPILE.fns.depositValidatorRewardsPool(
        acct.address, val, coin
    ).transact(w3, acct, to=DISTRIBUTION, gas=gas, check=False)
    # TODO: align disabled
    assert res.status == 1
    blk = res["blockNumber"]
    rsp = requests.get(f"{cli.node_rpc_http}/block_results?height={blk}").json()
    rsp = next((tx for tx in rsp["result"]["txs_results"] if tx["code"] == 0), None)
    data = find_log_event_attrs(
        rsp["events"], "rewards", lambda attrs: "amount" in attrs
    )
    assert parse_amount(data["amount"]) == fund_amount

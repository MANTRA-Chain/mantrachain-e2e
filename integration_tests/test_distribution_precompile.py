import pytest
from eth_contract.contract import Contract

from .utils import (
    ACCOUNTS,
    DEFAULT_DENOM,
    WEI_PER_DENOM,
    build_contract,
    find_fee,
    wait_for_block,
    wait_for_new_blocks,
)

pytestmark = pytest.mark.asyncio

PRECOMPILE = Contract(build_contract("DistributionI")["abi"])

DISTRIBUTION = "0x0000000000000000000000000000000000000801"

gas = 400_000


async def community_pool(w3):
    res = await PRECOMPILE.fns.communityPool().call(w3, to=DISTRIBUTION)
    return res[0][1] if res else 0


async def rewards(w3, val, val_addr):
    res = await PRECOMPILE.fns.delegationRewards(val, val_addr).call(
        w3, to=DISTRIBUTION
    )
    return res[0][1] if res else 0


@pytest.mark.connect
async def test_connect_distribution(connect_mantra, tmp_path):
    await test_distribution(None, connect_mantra, tmp_path)


async def test_distribution(mantra, connect_mantra, tmp_path):
    cli = connect_mantra.cosmos_cli(tmp_path)
    tax = cli.get_params("distribution")["params"]["community_tax"]
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
    community_af = await community_pool(w3)
    assert community_af - community_bf > fee


@pytest.mark.connect
async def test_connect_delegation_rewards_flow(connect_mantra, tmp_path):
    await test_delegation_rewards_flow(None, connect_mantra, tmp_path)


async def test_delegation_rewards_flow(mantra, connect_mantra, tmp_path):
    cli = connect_mantra.cosmos_cli(tmp_path)
    w3 = connect_mantra.async_w3
    name = "validator"
    acct = ACCOUNTS[name]
    val = cli.address(name, "val")
    initial_rewards = await rewards(w3, acct.address, val)

    signer2 = cli.address("signer2")
    rsp = cli.transfer(cli.address(name), signer2, f"1{DEFAULT_DENOM}")
    assert rsp["code"] == 0, rsp["raw_log"]

    # wait for rewards to accumulate
    wait_for_new_blocks(cli, 3)

    current_rewards = await rewards(w3, acct.address, val)
    assert current_rewards >= initial_rewards, "rewards should increase"

    balance_bf = await w3.eth.get_balance(acct.address)

    res = await PRECOMPILE.fns.claimRewards(acct.address, 1).transact(
        w3, acct, to=DISTRIBUTION, gas=gas
    )
    assert res.status == 1
    fee = res["gasUsed"] * res["effectiveGasPrice"]

    balance_af = await w3.eth.get_balance(acct.address)
    assert balance_af >= balance_bf - fee, "balance should account for rewards and fees"


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
    name = "validator"
    acct = ACCOUNTS[name]
    val = cli.address(name, "val")

    res = await PRECOMPILE.fns.setWithdrawAddress(
        acct.address, cli.address(name)
    ).transact(w3, acct, to=DISTRIBUTION, gas=gas)
    assert res.status == 1

    # fund validator rewards pool
    fund_amount = 100
    balance_bf = await w3.eth.get_balance(acct.address)
    coin = [[DEFAULT_DENOM, fund_amount]]
    res = await PRECOMPILE.fns.depositValidatorRewardsPool(
        acct.address, val, coin
    ).transact(w3, acct, to=DISTRIBUTION, gas=gas)
    assert res.status == 1

    balance_af = await w3.eth.get_balance(acct.address)
    fee = res["gasUsed"] * res["effectiveGasPrice"]
    assert (
        balance_af == balance_bf - fund_amount * WEI_PER_DENOM - fee
    ), "balance should decrease"

    res = await PRECOMPILE.fns.withdrawDelegatorRewards(acct.address, val).transact(
        w3, acct, to=DISTRIBUTION, gas=gas
    )
    assert res.status == 1

    withdraw_fee = res["gasUsed"] * res["effectiveGasPrice"]
    balance_last = await w3.eth.get_balance(acct.address)
    assert balance_last >= balance_af - withdraw_fee, "balance should increase"

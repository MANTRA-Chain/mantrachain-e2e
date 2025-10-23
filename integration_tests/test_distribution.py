import pytest

from .utils import (
    DEFAULT_DENOM,
    find_fee,
    wait_for_block,
    wait_for_new_blocks,
)

pytestmark = pytest.mark.slow


@pytest.mark.connect
def test_connect_distribution(connect_mantra, tmp_path):
    test_distribution(None, connect_mantra, tmp_path)


def test_distribution(mantra, connect_mantra, tmp_path):
    cli = connect_mantra.cosmos_cli(tmp_path)
    tax = cli.get_params("distribution")["params"]["community_tax"]
    if float(tax) < 0.01:
        pytest.skip(f"community_tax is {tax} too low for test")
    signer1, signer2 = cli.address("signer1"), cli.address("signer2")
    # wait for initial rewards
    wait_for_block(cli, 2)

    balance_bf = cli.balance(signer1)
    community_bf = cli.distribution_community_pool()
    amt = 2
    rsp = cli.transfer(signer1, signer2, f"{amt}{DEFAULT_DENOM}")
    assert rsp["code"] == 0, rsp["raw_log"]
    fee = find_fee(rsp)
    wait_for_new_blocks(cli, 2)
    assert cli.balance(signer1) == balance_bf - fee - amt
    assert cli.distribution_community_pool() - community_bf > fee


@pytest.mark.skip(reason="https://github.com/cosmos/cosmos-sdk/pull/25485")
def test_commission(mantra):
    cli = mantra.cosmos_cli()
    name = "validator"
    val = cli.address(name, "val")
    initial_commission = cli.distribution_commission(val)

    # wait for rewards to accumulate
    wait_for_new_blocks(cli, 3)

    current_commission = cli.distribution_commission(val)
    assert current_commission >= initial_commission, "commission should increase"
    balance_bf = cli.balance(name)

    rsp = cli.withdraw_validator_commission(val, from_=name)
    assert rsp["code"] == 0, rsp["raw_log"]

    balance_af = cli.balance(name)
    fee = find_fee(rsp)
    assert (
        balance_af >= balance_bf - fee
    ), "balance should increase after commission withdrawal"


@pytest.mark.connect
def test_connect_delegation_rewards_flow(connect_mantra, tmp_path):
    test_delegation_rewards_flow(None, connect_mantra, tmp_path)


def test_delegation_rewards_flow(mantra, connect_mantra, tmp_path):
    cli = connect_mantra.cosmos_cli(tmp_path)
    name = "validator"
    validator = cli.address(name)
    initial_rewards = cli.distribution_reward(validator)

    signer2 = cli.address("signer2")
    rsp = cli.transfer(validator, signer2, f"1{DEFAULT_DENOM}")
    assert rsp["code"] == 0, rsp["raw_log"]

    # wait for rewards to accumulate
    wait_for_new_blocks(cli, 3)

    current_rewards = cli.distribution_reward(validator)
    assert current_rewards >= initial_rewards, "rewards should increase"

    balance_bf = cli.balance(validator)
    rsp = cli.withdraw_rewards(cli.address(name, "val"), from_=name)
    assert rsp["code"] == 0, rsp["raw_log"]

    balance_af = cli.balance(validator)
    fee = find_fee(rsp)
    assert balance_af >= balance_bf - fee, "balance should account for rewards and fees"


@pytest.mark.connect
def test_connect_community_pool_funding(connect_mantra, tmp_path):
    test_community_pool_funding(None, connect_mantra, tmp_path)


def test_community_pool_funding(mantra, connect_mantra, tmp_path):
    cli = connect_mantra.cosmos_cli(tmp_path)
    signer1 = cli.address("signer1")
    initial_pool = cli.distribution_community_pool()

    fund_amount = 1000
    balance_bf = cli.balance(signer1)
    rsp = cli.fund_community_pool(f"{fund_amount}{DEFAULT_DENOM}", from_=signer1)
    assert rsp["code"] == 0, rsp["raw_log"]

    balance_af = cli.balance(signer1)
    fee = find_fee(rsp)
    assert balance_af == balance_bf - fund_amount - fee, "balance should decrease"

    final_pool = cli.distribution_community_pool()
    assert final_pool >= initial_pool + fund_amount, "community pool should increase"


def test_validator_rewards_pool_funding(mantra):
    cli = mantra.cosmos_cli()
    name = "validator"
    val = cli.address(name, "val")

    rsp = cli.set_withdraw_addr(cli.address(name), from_=name)
    assert rsp["code"] == 0, rsp["raw_log"]

    # fund validator rewards pool
    fund_amount = 100
    balance_bf = cli.balance(name)
    rsp = cli.fund_validator_rewards_pool(
        val, f"{fund_amount}{DEFAULT_DENOM}", from_=name
    )
    assert rsp["code"] == 0, rsp["raw_log"]

    balance_af = cli.balance(name)
    fee = find_fee(rsp)
    assert balance_af == balance_bf - fund_amount - fee, "balance should decrease"

    rsp = cli.withdraw_rewards(val, from_=name)
    assert rsp["code"] == 0, rsp["raw_log"]

    balance_last = cli.balance(name)
    withdraw_fee = find_fee(rsp)
    assert balance_last >= balance_af - withdraw_fee, "balance should increase"

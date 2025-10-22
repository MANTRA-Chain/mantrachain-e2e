import pytest

from .utils import (
    DEFAULT_DENOM,
    find_fee,
    wait_for_block,
    wait_for_new_blocks,
)

pytestmark = pytest.mark.slow


def test_distribution(mantra):
    cli = mantra.cosmos_cli()
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
    validator_name = "validator"
    validator = cli.address(validator_name)
    val_addr = cli.address(validator_name, "val")
    initial_commission = cli.distribution_commission(val_addr)

    # wait for rewards to accumulate
    wait_for_new_blocks(cli, 3)

    current_commission = cli.distribution_commission(val_addr)
    assert current_commission >= initial_commission, "commission should increase"
    balance_bf = cli.balance(validator_name)

    rsp = cli.withdraw_validator_commission(val_addr, from_=validator)
    assert rsp["code"] == 0, rsp["raw_log"]

    balance_af = cli.balance(validator_name)
    fee = find_fee(rsp)
    assert (
        balance_af >= balance_bf - fee
    ), "balance should increase after commission withdrawal"


def test_delegation_rewards_flow(mantra):
    cli = mantra.cosmos_cli()
    validator_name = "validator"
    validator = cli.address(validator_name)
    val_addr = cli.address(validator_name, "val")
    initial_rewards = cli.distribution_reward(validator)

    signer2 = cli.address("signer2")
    rsp = cli.transfer(validator, signer2, f"1{DEFAULT_DENOM}")
    assert rsp["code"] == 0, rsp["raw_log"]

    # wait for rewards to accumulate
    wait_for_new_blocks(cli, 3)

    current_rewards = cli.distribution_reward(validator)
    assert current_rewards >= initial_rewards, "rewards should increase"

    balance_bf = cli.balance(validator)
    rsp = cli.withdraw_rewards(val_addr, from_=validator)
    assert rsp["code"] == 0, rsp["raw_log"]

    balance_af = cli.balance(validator)
    fee = find_fee(rsp)
    assert balance_af >= balance_bf - fee, "balance should account for rewards and fees"


def test_community_pool_funding(mantra):
    cli = mantra.cosmos_cli()
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
    validator_name = "validator"
    val_addr = cli.address(validator_name, "val")

    rsp = cli.set_withdraw_addr(cli.address(validator_name), from_=validator_name)
    assert rsp["code"] == 0, rsp["raw_log"]

    # fund validator rewards pool
    fund_amount = 100
    balance_bf = cli.balance(validator_name)
    rsp = cli.fund_validator_rewards_pool(
        val_addr, f"{fund_amount}{DEFAULT_DENOM}", from_=validator_name
    )
    assert rsp["code"] == 0, rsp["raw_log"]

    balance_af = cli.balance(validator_name)
    fee = find_fee(rsp)
    assert balance_af == balance_bf - fund_amount - fee, "balance should decrease"

    rsp = cli.withdraw_rewards(val_addr, from_=validator_name)
    assert rsp["code"] == 0, rsp["raw_log"]

    balance_after_withdraw = cli.balance(validator_name)
    withdraw_fee = find_fee(rsp)
    assert (
        balance_after_withdraw >= balance_af - withdraw_fee
    ), "balance should increase"

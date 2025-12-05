import pytest
import requests
from pystarport.utils import (
    parse_amount,
    wait_for_block,
    wait_for_new_blocks,
)

from .utils import (
    DEFAULT_DENOM,
    find_fee,
    find_log_event_attrs,
)

pytestmark = pytest.mark.slow


@pytest.mark.connect
def test_connect_distribution(connect_mantra, tmp_path):
    test_distribution(None, connect_mantra, tmp_path)


def test_distribution(mantra, connect_mantra, tmp_path):
    cli = connect_mantra.cosmos_cli(tmp_path)
    tax = cli.get_params("distribution")["community_tax"]
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
    assert cli.distribution_community_pool() > community_bf


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


def test_delegation_rewards_flow(mantra):
    cli = mantra.cosmos_cli()
    val = cli.address("validator", "val")
    validator = cli.address("validator")
    delegate_amt = 20_000_000
    gas0 = 250_000
    coin = f"{delegate_amt}{DEFAULT_DENOM}"
    signer1 = cli.address("signer1")
    signer2 = cli.address("signer2")

    rsp = cli.set_withdraw_addr(signer2, from_=signer1)
    assert rsp["code"] == 0, rsp["raw_log"]

    rsp = cli.delegate_amount(val, coin, _from=signer1, gas=gas0)
    assert rsp["code"] == 0, rsp["raw_log"]
    height = int(rsp["height"])

    rsp = cli.delegate_amount(val, coin, _from=validator, gas=gas0)
    assert rsp["code"] == 0, rsp["raw_log"]

    wait_for_new_blocks(cli, 3)

    rewards = [
        cli.distribution_rewards(signer1, height=height),
        cli.distribution_rewards(signer1),
    ]
    assert rewards[1] >= rewards[0], "rewards should increase"

    period = cli.query_delegator_starting_info(signer1, val)["previous_period"]
    start = parse_amount(
        cli.query_validator_historical_rewards(val, period).get(
            "cumulative_reward_ratio", [{}]
        )[0]
    )

    rsp = cli.withdraw_rewards(val, from_=signer1)
    assert rsp["code"] == 0, rsp["raw_log"]
    height = int(rsp["height"])
    period = cli.query_delegator_starting_info(signer1, val, height=height)[
        "previous_period"
    ]
    end = parse_amount(
        cli.query_validator_historical_rewards(val, period, height=height).get(
            "cumulative_reward_ratio", [{}]
        )[0]
    )
    balances = [
        cli.balance(signer2, height=height - 1),
        cli.balance(signer2, height=height),
    ]
    assert int(delegate_amt * (end - start)) == balances[1] - balances[0]


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


@pytest.mark.connect
def test_connect_validator_rewards_pool_funding(connect_mantra, tmp_path):
    test_validator_rewards_pool_funding(None, connect_mantra, tmp_path)


@pytest.mark.skipped
def test_validator_rewards_pool_funding(mantra, connect_mantra, tmp_path):
    cli = connect_mantra.cosmos_cli(tmp_path)
    signer1 = cli.address("signer1")
    val = cli.validators()[0]["operator_address"]
    fund_amount = 1000
    rsp = cli.fund_validator_rewards_pool(
        val, f"{fund_amount}{DEFAULT_DENOM}", from_=signer1
    )
    disabled = (
        "/cosmos.distribution.v1beta1.MsgDepositValidatorRewardsPool"
        in cli.query_disabled_list()
    )
    if disabled:
        assert rsp["code"] != 0, rsp["raw_log"]
        assert "tx type not allowed" in rsp["raw_log"]
    else:
        assert rsp["code"] == 0, rsp["raw_log"]
        blk = rsp["height"]
        rsp = requests.get(f"{cli.node_rpc_http}/block_results?height={blk}").json()
        rsp = next((tx for tx in rsp["result"]["txs_results"] if tx["code"] == 0), None)
        data = find_log_event_attrs(
            rsp["events"], "rewards", lambda attrs: "amount" in attrs
        )
        assert parse_amount(data["amount"]) == fund_amount

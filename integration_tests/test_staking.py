from datetime import timedelta

from dateutil.parser import isoparse

from .utils import DEFAULT_DENOM, find_fee, find_log_event_attrs, wait_for_block_time


def test_staking_delegate(mantra):
    cli = mantra.cosmos_cli()
    name = "signer1"
    amt = 2
    bonded_bf = cli.staking_pool()
    balance_bf = cli.balance(name)
    validator = cli.validators()[0]["operator_address"]
    rsp = cli.delegate_amount(validator, f"{amt}{DEFAULT_DENOM}", _from=name)
    fee = find_fee(rsp)
    assert cli.staking_pool() == bonded_bf + amt
    assert balance_bf == cli.balance(name) + amt + fee


def test_staking_unbond(mantra):
    cli = mantra.cosmos_cli()
    name = "signer1"
    signer1 = cli.address(name)
    validators = cli.validators()
    val_ops = [v["operator_address"] for v in validators[:2]]
    balance_bf = cli.balance(signer1)
    bonded_bf = cli.staking_pool()
    amounts = [3, 4]
    fee = 0

    for i, amt in enumerate(amounts):
        rsp = cli.delegate_amount(val_ops[i], f"{amt}{DEFAULT_DENOM}", _from=name)
        assert rsp["code"] == 0, rsp["raw_log"]
        fee += find_fee(rsp)

    assert cli.staking_pool() == bonded_bf + sum(amounts)
    assert cli.balance(signer1) == balance_bf - sum(amounts) - fee

    unbonded = cli.staking_pool(bonded=False)
    unbonded_amt = 2
    rsp = cli.unbond_amount(
        val_ops[1], f"{unbonded_amt}{DEFAULT_DENOM}", _from=name, gas=220_000
    )
    assert rsp["code"] == 0, rsp
    fee += find_fee(rsp)
    assert cli.staking_pool(bonded=False) == unbonded + unbonded_amt
    data = find_log_event_attrs(
        rsp["events"], "unbond", lambda attrs: "completion_time" in attrs
    )
    wait_for_block_time(cli, isoparse(data["completion_time"]) + timedelta(seconds=1))
    assert cli.balance(signer1) == balance_bf - (sum(amounts) - unbonded_amt) - fee

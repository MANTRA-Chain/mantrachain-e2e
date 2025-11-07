from .utils import DEFAULT_DENOM, find_fee


def test_fee_allowance_flow(mantra):
    cli = mantra.cosmos_cli()
    amt = 100
    granter = cli.address("community")
    grantee = cli.address("signer1")
    receiver = cli.address("signer2")

    fee_granter_balance = cli.balance(granter)
    fee_grantee_balance = cli.balance(grantee)
    receiver_balance = cli.balance(receiver)

    rsp = cli.grant_fee_allowance(granter, grantee)
    assert rsp["code"] == 0, rsp["raw_log"]
    fee = find_fee(rsp)

    rsp = cli.transfer(grantee, receiver, f"{amt}{DEFAULT_DENOM}", fee_granter=granter)
    assert rsp["code"] == 0, rsp["raw_log"]
    fee += find_fee(rsp)

    assert cli.balance(granter) == fee_granter_balance - fee
    assert cli.balance(grantee) == fee_grantee_balance - amt
    assert cli.balance(receiver) == receiver_balance + amt

    fee_grant_spend_limit = 5
    fee_granter_balance = cli.balance(granter)
    fee_grantee_balance = cli.balance(grantee)
    receiver_balance = cli.balance(receiver)

    rsp = cli.revoke_fee_grant(granter, grantee)
    assert rsp["code"] == 0, rsp["raw_log"]
    fee = find_fee(rsp)

    rsp = cli.grant_fee_allowance(
        granter, grantee, spend_limit=f"{fee_grant_spend_limit}{DEFAULT_DENOM}"
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    fee += find_fee(rsp)

    rsp = cli.transfer(grantee, receiver, f"{amt}{DEFAULT_DENOM}", fee_granter=granter)
    assert rsp["code"] != 0, "should fail as fee limit exceeded"

    assert cli.balance(granter) == fee_granter_balance - fee
    assert cli.balance(grantee) == fee_grantee_balance
    assert cli.balance(receiver) == receiver_balance

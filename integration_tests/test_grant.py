import pytest

from .utils import DEFAULT_DENOM, find_fee

pytestmark = pytest.mark.skipped


def test_flow(mantra):
    cli = mantra.cosmos_cli()
    amt = 100
    granter = cli.address("community")
    grantee = cli.address("signer1")
    receiver = cli.address("signer2")

    # grant_fee_allowance
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

    # grant_authorization
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
    )
    assert rsp["code"] == 0, rsp["raw_log"]

    def find_grant(auth_type):
        grants = cli.query_grants(granter, grantee)
        return next(
            (g for g in grants if g["authorization"]["type"] == auth_type), None
        )

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
    )
    assert rsp["code"] == 0, rsp["raw_log"]

    send_grant = find_grant("/cosmos.bank.v1beta1.SendAuthorization")
    assert send_grant and send_grant["authorization"]["value"]["spend_limit"][0][
        "amount"
    ] == str(spend_limit)

    msg_type = "/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward"
    rsp = cli.grant_authorization(
        grantee,
        "generic",
        from_=granter,
        msg_type=msg_type,
    )
    assert rsp["code"] == 0

    generic_grant = find_grant("/cosmos.authz.v1beta1.GenericAuthorization")
    assert generic_grant and generic_grant["authorization"]["value"]["msg"] == msg_type

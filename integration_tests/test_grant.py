import json

import pytest

from .utils import (
    DEFAULT_DENOM,
    assert_grant_authorizations,
    find_fee,
    find_grant,
    send_grant_spend_limit,
)

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
    assert_grant_authorizations(cli, granter, grantee, spend_limit=200)

    msg_type = "/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward"
    rsp = cli.grant_authorization(
        grantee,
        "generic",
        from_=granter,
        msg_type=msg_type,
    )
    assert rsp["code"] == 0, rsp["raw_log"]

    generic_grant = find_grant(
        cli, granter, grantee, "/cosmos.authz.v1beta1.GenericAuthorization"
    )
    assert generic_grant["msg"] == msg_type


def test_authz_spend_limit_atomicity(mantra, tmp_path):
    cli = mantra.cosmos_cli()
    granter = cli.address("signer1")
    grantee = cli.address("signer2")
    receiver = cli.address("community")

    granter_balance = cli.balance(granter)
    send_amount = granter_balance + 1000
    grant_limit = send_amount + 1000

    rsp = cli.grant_authorization(
        grantee,
        "send",
        from_=granter,
        spend_limit=f"{grant_limit}{DEFAULT_DENOM}",
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    assert send_grant_spend_limit(cli, granter, grantee) == grant_limit

    tx = cli.transfer(
        granter,
        receiver,
        f"{send_amount}{DEFAULT_DENOM}",
        generate_only=True,
    )

    tx_file = tmp_path / "tx.json"
    tx_file.write_text(json.dumps(tx))
    rsp = cli.exec_tx_by_grantee(tx_file, from_=grantee)
    assert rsp["code"] != 0
    assert "insufficient funds" in rsp.get("raw_log", "")

    spend_limit = send_grant_spend_limit(cli, granter, grantee)
    assert (
        spend_limit == grant_limit
    ), f"spendLimit changed from {grant_limit} to {spend_limit} despite exec failure."

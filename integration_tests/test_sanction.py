import json

import pytest
import web3

from .utils import (
    DEFAULT_DENOM,
    WEI_PER_DENOM,
    approve_proposal,
    assert_transfer,
    bech32_to_eth,
    module_address,
    submit_gov_proposal,
)

pytestmark = pytest.mark.slow


def test_blacklist(mantra, tmp_path):
    cli = mantra.cosmos_cli()
    if not cli.has_module("wasm"):
        pytest.skip("sanction module not enabled")
    community = cli.address("community")
    user = cli.create_account("user")["address"]
    grantee = cli.create_account("grantee")["address"]
    amt = 90_000_000_000_000_000 // WEI_PER_DENOM
    assert_transfer(cli, community, user, amt=amt)

    # should revoke these grants once `user` is blacklisted
    rsp = cli.grant_authorization(
        grantee,
        "send",
        from_=user,
        spend_limit=f"1{DEFAULT_DENOM}",
    )
    assert rsp["code"] == 0, rsp["raw_log"]

    msg_type = "/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward"
    rsp = cli.grant_authorization(
        grantee,
        "generic",
        from_=user,
        msg_type=msg_type,
    )
    assert rsp["code"] == 0, rsp["raw_log"]

    grants_bf = cli.query_grants(user, grantee)
    assert any(
        g["authorization"]["type"] == "/cosmos.bank.v1beta1.SendAuthorization"
        for g in grants_bf
    )
    assert any(
        g["authorization"]["type"] == "/cosmos.authz.v1beta1.GenericAuthorization"
        and g["authorization"]["value"]["msg"] == msg_type
        for g in grants_bf
    )
    msg = {
        "@type": "/mantrachain.sanction.v1.MsgAddBlacklistAccounts",
        "authority": module_address("gov"),
        "blacklist_accounts": [user],
    }
    proposal_src = {
        "title": "title",
        "summary": "summary",
        "deposit": f"1{DEFAULT_DENOM}",
        "messages": [msg],
    }
    proposal = tmp_path / "proposal.json"
    proposal.write_text(json.dumps(proposal_src))
    gov_rsp = cli.submit_gov_proposal(proposal, from_="community")
    assert gov_rsp["code"] == 0, gov_rsp["raw_log"]
    approve_proposal(mantra, gov_rsp["events"])
    assert user in cli.query_blacklist()
    assert cli.query_grants(user, grantee) == []

    err = f"{bech32_to_eth(user)} is blacklisted"
    with pytest.raises(web3.exceptions.Web3RPCError, match=err):
        mantra.w3.eth.send_transaction(
            {
                "from": bech32_to_eth(user),
                "to": bech32_to_eth(community),
                "value": 1000,
            }
        )

    msg["@type"] = "/mantrachain.sanction.v1.MsgRemoveBlacklistAccounts"
    submit_gov_proposal(mantra, tmp_path, messages=[msg])
    assert_transfer(cli, user, community)

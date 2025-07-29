import json

import pytest
import web3

from .utils import (
    DEFAULT_DENOM,
    approve_proposal,
    assert_transfer,
    bech32_to_eth,
    eth_to_bech32,
    find_fee,
    module_address,
    submit_gov_proposal,
)

pytestmark = pytest.mark.slow


def grant_authorization(cli, granter, grantee, spend_limit):
    rsp = cli.grant_authorization(
        grantee,
        "send",
        granter,
        spend_limit="%s%s" % (spend_limit, DEFAULT_DENOM),
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    return find_fee(rsp)


def exec_tx_by_grantee(cli, tmp_path, granter, grantee, receiver, amt):
    generated_tx_txt = tmp_path / "generated_tx.txt"
    with open(generated_tx_txt, "w") as opened_file:
        generated_tx_msg = cli.transfer(
            granter,
            receiver,
            "%s%s" % (amt, DEFAULT_DENOM),
            generate_only=True,
        )
        json.dump(generated_tx_msg, opened_file)

    rsp = cli.exec_tx_by_grantee(
        generated_tx_txt,
        grantee,
    )
    assert rsp["code"] == 0, rsp["raw_log"]


def test_blacklist(mantra, tmp_path):
    cli = mantra.cosmos_cli()
    community = cli.address("community")
    granter = cli.create_account("user")["address"]
    grantee = cli.address("signer1")
    receiver = cli.address("signer2")
    assert_transfer(cli, community, granter, amt=20000)
    msg = {
        "@type": "/mantrachain.sanction.v1.MsgAddBlacklistAccounts",
        "authority": eth_to_bech32(module_address("gov")),
        "blacklist_accounts": [granter],
    }
    proposal_src = {
        "title": "title",
        "summary": "summary",
        "deposit": f"1{DEFAULT_DENOM}",
        "messages": [msg],
    }
    proposal = tmp_path / "proposal.json"
    proposal.write_text(json.dumps(proposal_src))
    rsp = cli.submit_gov_proposal(proposal, from_="community")
    assert rsp["code"] == 0, rsp["raw_log"]

    granter_balance = cli.balance(granter)
    receiver_balance = cli.balance(receiver)
    spend_limit = 200
    fee = grant_authorization(cli, granter, grantee, spend_limit)
    grants = cli.query_grants(granter, grantee)
    assert len(grants) == 1
    assert grants[0]["authorization"]["value"]["spend_limit"][0]["amount"] == "200"

    approve_proposal(mantra, rsp["events"])
    assert granter in cli.query_blacklist()
    assert not cli.query_blacklist(limit=1, page=100)
    with pytest.raises(AssertionError, match=f"{granter} is blacklisted"):
        assert_transfer(cli, granter, community)

    amt = spend_limit // 2
    exec_tx_by_grantee(cli, tmp_path, granter, grantee, receiver, amt)
    assert cli.balance(granter) == granter_balance - amt - fee
    assert cli.balance(receiver) == receiver_balance + amt

    err = f"{granter} is blacklisted"
    with pytest.raises(web3.exceptions.Web3RPCError, match=err):
        mantra.w3.eth.send_transaction(
            {
                "from": bech32_to_eth(granter),
                "to": bech32_to_eth(community),
                "value": 1000,
            }
        )

    msg["@type"] = "/mantrachain.sanction.v1.MsgRemoveBlacklistAccounts"
    submit_gov_proposal(mantra, tmp_path, messages=[msg])
    assert_transfer(cli, granter, community)

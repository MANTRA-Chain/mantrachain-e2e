import json

import pytest
import web3

from .utils import (
    DEFAULT_DENOM,
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
    assert_transfer(cli, community, user, amt=20000)
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

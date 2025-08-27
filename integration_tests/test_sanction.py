import json

import pytest
import web3

from .utils import (
    DEFAULT_DENOM,
    DEFAULT_GAS_PRICE,
    approve_proposal,
    assert_transfer,
    bech32_to_eth,
    find_fee,
    module_address,
    submit_gov_proposal,
    wait_for_new_blocks,
)

pytestmark = pytest.mark.slow


def test_blacklist(mantra, tmp_path):
    cli = mantra.cosmos_cli()
    community = cli.address("community")
    granter = cli.create_account("user")["address"]
    grantee = cli.address("signer1")
    receiver = cli.address("signer2")
    assert_transfer(cli, community, granter, amt=20000)
    msg = {
        "@type": "/mantrachain.sanction.v1.MsgAddBlacklistAccounts",
        "authority": module_address("gov"),
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
    gov_rsp = cli.submit_gov_proposal(proposal, from_="community")
    assert gov_rsp["code"] == 0, gov_rsp["raw_log"]

    receiver_balance = cli.balance(receiver)
    spend_limit = 200
    rsp = cli.grant_authorization(
        grantee,
        "send",
        from_=granter,
        spend_limit="%s%s" % (spend_limit, DEFAULT_DENOM),
    )
    assert rsp["code"] == 0, rsp["raw_log"]

    grants = cli.query_grants(granter, grantee)
    assert len(grants) == 1
    assert grants[0]["authorization"]["value"]["spend_limit"][0]["amount"] == "200"

    delegate_coins = 10000
    validator_address = cli.address("validator", "val")
    assert cli.distribution_reward(granter) == 0
    gas_prices = DEFAULT_GAS_PRICE
    rsp = cli.delegate_amount(
        validator_address,
        "%s%s" % (delegate_coins, DEFAULT_DENOM),
        from_=granter,
        gas_prices=gas_prices,
    )
    fee = find_fee(rsp)
    assert rsp["code"] == 0

    # wait for some reward
    wait_for_new_blocks(cli, 2)

    msg_type = "/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward"
    rsp = cli.grant_authorization(
        grantee,
        "generic",
        from_=granter,
        msg_type=msg_type,
    )
    fee += find_fee(rsp)
    assert rsp["code"] == 0

    generated_tx_txt = tmp_path / "generated_tx.txt"
    generated_tx_msg = cli.withdraw_all_rewards(
        from_=granter,
        generate_only=True,
    )
    with open(generated_tx_txt, "w") as opened_file:
        json.dump(generated_tx_msg, opened_file)

    approve_proposal(mantra, gov_rsp["events"])
    assert granter in cli.query_blacklist()
    assert not cli.query_blacklist(limit=1, page=100)

    rewards1 = cli.distribution_reward(granter)
    balance1 = cli.balance(granter)
    rsp = cli.exec_tx_by_grantee(
        generated_tx_txt,
        from_=grantee,
    )
    assert rsp["code"] == 0
    wait_for_new_blocks(cli, 1)
    balance = cli.balance(granter)
    assert balance == balance1 + int(rewards1 + cli.distribution_reward(granter))

    with pytest.raises(AssertionError, match=f"{granter} is blacklisted"):
        assert_transfer(cli, granter, community)

    amt = spend_limit // 2
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
        from_=grantee,
    )
    assert rsp["code"] == 0, rsp["raw_log"]

    assert cli.balance(granter) == balance - amt
    assert cli.balance(receiver) == receiver_balance + amt

    err = f"{bech32_to_eth(granter)} is blacklisted"
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

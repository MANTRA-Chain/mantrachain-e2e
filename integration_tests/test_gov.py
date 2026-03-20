import json

import pytest
from eth_contract.erc20 import ERC20
from pystarport.utils import wait_for_new_blocks

from .utils import (
    ADDRS,
    DEFAULT_DENOM,
    WETH_ADDRESS,
    approve_proposal,
    assert_burn_tokenfactory_denom,
    assert_create_erc20_denom,
    assert_create_tokenfactory_denom,
    assert_mint_tokenfactory_denom,
    assert_transfer_tokenfactory_denom,
    find_log_event_attrs,
    module_address,
    submit_gov_proposal,
)


@pytest.mark.slow
def test_submit_any_proposal(mantra, tmp_path):
    # governance module account as granter
    cli = mantra.cosmos_cli()
    granter_addr = module_address("gov")
    grantee_addr = cli.address("signer1")

    # this json can be obtained with `--generate-only` flag for respective cli calls
    proposal_json = {
        "messages": [
            {
                "@type": "/cosmos.feegrant.v1beta1.MsgGrantAllowance",
                "granter": granter_addr,
                "grantee": grantee_addr,
                "allowance": {
                    "@type": "/cosmos.feegrant.v1beta1.BasicAllowance",
                    "spend_limit": [],
                    "expiration": None,
                },
            }
        ],
        "deposit": f"1{DEFAULT_DENOM}",
        "title": "title",
        "summary": "summary",
    }
    proposal_file = tmp_path / "proposal.json"
    proposal_file.write_text(json.dumps(proposal_json))
    rsp = cli.submit_gov_proposal(proposal_file, from_="community", gas=210000)
    assert rsp["code"] == 0, rsp["raw_log"]
    approve_proposal(mantra, rsp["events"])
    grant_detail = cli.query_grant(granter_addr, grantee_addr)
    assert grant_detail["granter"] == granter_addr
    assert grant_detail["grantee"] == grantee_addr


@pytest.mark.slow
def test_gov_proposal(mantra, tmp_path):
    cli = mantra.cosmos_cli()
    proposer = cli.address("community")
    voter = cli.address("signer1")

    msg = {
        "@type": "/cosmos.bank.v1beta1.MsgSetSendEnabled",
        "authority": module_address("gov"),
        "send_enabled": [{"denom": DEFAULT_DENOM, "enabled": True}],
    }
    proposal = {
        "title": "test",
        "summary": "test",
        "deposit": f"1{DEFAULT_DENOM}",
        "messages": [msg],
    }
    proposal_file = tmp_path / "proposal_full_cli.json"
    proposal_file.write_text(json.dumps(proposal))

    rsp = cli.submit_gov_proposal(proposal_file, from_="community", gas=400000)
    assert rsp["code"] == 0, rsp["raw_log"]
    ev = find_log_event_attrs(
        rsp["events"], "submit_proposal", lambda attrs: "proposal_id" in attrs
    )
    assert ev is not None, rsp["events"]
    proposal_id = ev["proposal_id"]

    rsp = cli.gov_deposit(proposal_id, f"1{DEFAULT_DENOM}", from_="signer1")
    assert rsp["code"] == 0, rsp["raw_log"]

    rsp = cli.gov_weighted_vote(
        proposal_id, "yes=0.5,no=0.3,abstain=0.2", from_="signer1"
    )
    assert rsp["code"] == 0, rsp["raw_log"]

    wait_for_new_blocks(cli, 1)

    prop = cli.query_proposal(proposal_id)
    assert str(prop["id"]) == str(proposal_id)
    assert prop["title"] == proposal["title"]

    vote = cli.query_vote(proposal_id, voter)
    assert str(vote.get("proposal_id")) == str(proposal_id)
    assert vote.get("voter") == voter

    proposer_deposit = cli.query_gov_deposit(proposal_id, proposer)
    assert str(proposer_deposit.get("proposal_id")) == str(proposal_id)
    assert proposer_deposit.get("depositor") == proposer

    voter_deposit = cli.query_gov_deposit(proposal_id, voter)
    assert str(voter_deposit.get("proposal_id")) == str(proposal_id)
    assert voter_deposit.get("depositor") == voter

    tally = cli.query_tally(proposal_id)
    tally = tally.get("tally") or tally
    assert len(tally) >= 4

    rsp = cli.gov_cancel_proposal(proposal_id, from_="community")
    assert rsp["code"] == 0, rsp["raw_log"]


def normalize(lst):
    return {tuple(sorted(d.items())) for d in lst}


@pytest.mark.slow
def test_history_serve_window(mantra, tmp_path):
    cli = mantra.cosmos_cli()
    p = cli.get_params("evm")
    updated = 4096
    p["history_serve_window"] = updated
    submit_gov_proposal(
        mantra,
        tmp_path,
        messages=[
            {
                "@type": "/cosmos.evm.vm.v1.MsgUpdateParams",
                "authority": module_address("gov"),
                "params": p,
            },
        ],
        gas=300_000,
    )
    p = cli.get_params("evm")
    assert int(p["history_serve_window"]) == int(updated), p


@pytest.mark.asyncio
async def test_submit_send_enabled(mantra, tmp_path):
    cli = mantra.cosmos_cli()
    community = ADDRS["community"]
    w3 = mantra.async_w3
    erc20_denom, total = await assert_create_erc20_denom(w3, community)
    # check create mint transfer and burn tokenfactory denom
    sender = cli.address("community")
    receiver = cli.address("reserve")
    subdenom = "test"
    gas = 300000
    amt = 10**6
    transfer_amt = 1
    burn_amt = 10**3
    denom = assert_create_tokenfactory_denom(cli, subdenom, _from=sender, gas=620000)
    assert_mint_tokenfactory_denom(cli, denom, amt, _from=sender, gas=gas)
    assert_transfer_tokenfactory_denom(
        cli, denom, receiver, transfer_amt, _from=sender, gas=gas
    )
    assert_burn_tokenfactory_denom(cli, denom, burn_amt, _from=sender, gas=gas)

    # check disable send for denom
    assert len(cli.query_bank_send()) == 0, "should be empty"
    send_enable = [
        {"denom": DEFAULT_DENOM, "enabled": True},
        {"denom": denom},
        {"denom": erc20_denom, "enabled": True},
    ]
    submit_gov_proposal(
        mantra,
        tmp_path,
        messages=[
            {
                "@type": "/cosmos.evm.erc20.v1.MsgRegisterERC20",
                "signer": module_address("gov"),
                "erc20addresses": [WETH_ADDRESS],
            },
            {
                "@type": "/cosmos.bank.v1beta1.MsgSetSendEnabled",
                "authority": module_address("gov"),
                "sendEnabled": send_enable,
            },
        ],
        gas=gas,
    )
    assert normalize(cli.query_bank_send()) == normalize(send_enable)
    disabled_err = "send transactions are disabled"

    # compare balance after convert all erc20
    rsp = cli.convert_erc20(WETH_ADDRESS, total, _from=sender, gas=999999)
    assert rsp["code"] == 0, rsp["raw_log"]
    assert cli.balance(sender, erc20_denom) == total
    assert await ERC20.fns.balanceOf(community).call(w3, to=WETH_ADDRESS) == 0

    rsp = cli.transfer(sender, receiver, f"1{erc20_denom}")
    assert rsp["code"] == 0

    rsp = cli.transfer(sender, receiver, f"1{denom}")
    assert rsp["code"] != 0
    assert disabled_err in rsp["raw_log"]

    # check mint and burn again
    coin = f"{amt}{denom}"
    rsp = cli.mint_tokenfactory_denom(coin, _from=sender, gas=gas)
    assert rsp["code"] != 0
    err_msg = f"{denom} has been disabled"
    assert err_msg in rsp["raw_log"]
    coin = f"{burn_amt}{denom}"
    rsp = cli.burn_tokenfactory_denom(coin, _from=sender, gas=gas)
    assert rsp["code"] != 0
    assert err_msg in rsp["raw_log"]

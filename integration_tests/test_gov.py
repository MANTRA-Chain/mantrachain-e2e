import json

import pytest
from eth_contract.erc20 import ERC20

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


def normalize(lst):
    return {tuple(sorted(d.items())) for d in lst}


@pytest.mark.slow
def test_history_serve_window(mantra, tmp_path):
    cli = mantra.cosmos_cli()
    p = cli.get_params("evm")["params"]
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
    )
    p = cli.get_params("evm")["params"]
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
        {"denom": erc20_denom},
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
    rsp = cli.convert_erc20(WETH_ADDRESS, total, _from=sender, gas=999999)
    assert rsp["code"] == 0, rsp["raw_log"]
    assert cli.balance(sender, erc20_denom) == total
    assert await ERC20.fns.balanceOf(community).call(w3, to=WETH_ADDRESS) == 0

    rsp = cli.transfer(sender, receiver, f"1{erc20_denom}")
    disabled_err = "send transactions are disabled"
    assert rsp["code"] != 0
    assert disabled_err in rsp["raw_log"]

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

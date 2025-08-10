import pytest

from .utils import (
    DEFAULT_DENOM,
    assert_burn_tokenfactory_denom,
    assert_create_tokenfactory_denom,
    assert_mint_tokenfactory_denom,
    assert_transfer_tokenfactory_denom,
    module_address,
    submit_any_proposal,
    submit_gov_proposal,
)

pytestmark = pytest.mark.slow


def test_submit_any_proposal(mantra, tmp_path):
    submit_any_proposal(mantra, tmp_path)


def test_submit_send_enabled(mantra, tmp_path):
    cli = mantra.cosmos_cli()
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
    denoms = [DEFAULT_DENOM, denom]
    assert len(cli.query_bank_send(*denoms)) == 0, "should be empty"
    send_enable = [
        {"denom": DEFAULT_DENOM, "enabled": True},
        {"denom": denom},
    ]
    submit_gov_proposal(
        mantra,
        tmp_path,
        messages=[
            {
                "@type": "/cosmos.bank.v1beta1.MsgSetSendEnabled",
                "authority": module_address("gov"),
                "sendEnabled": send_enable,
            }
        ],
    )
    assert cli.query_bank_send(*denoms) == send_enable
    rsp = cli.transfer(sender, receiver, f"1{denom}")
    assert rsp["code"] != 0
    assert "send transactions are disabled" in rsp["raw_log"]
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

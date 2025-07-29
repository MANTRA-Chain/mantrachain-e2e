import hashlib

import pytest
from eth_utils import to_checksum_address

from .utils import (
    DEFAULT_DENOM,
    eth_to_bech32,
    find_log_event_attrs,
    module_address,
    submit_any_proposal,
    submit_gov_proposal,
)

pytestmark = pytest.mark.slow


def test_submit_any_proposal(mantra, tmp_path):
    submit_any_proposal(mantra, tmp_path)


def denom_to_erc20_address(denom):
    denom_hash = hashlib.sha256(denom.encode()).digest()
    return to_checksum_address("0x" + denom_hash[-20:].hex())


def test_submit_send_enabled(mantra, tmp_path):
    cli = mantra.cosmos_cli()
    sender = "community"
    addr_a = cli.address(sender)
    addr_b = cli.address("reserve")
    subdenom = "test"
    transfer_amt = 1
    gas = 300000
    # check create tokenfactory denom
    rsp = cli.create_tokenfactory_denom(subdenom, _from=sender, gas=600000)
    assert rsp["code"] == 0, rsp["raw_log"]
    event = find_log_event_attrs(
        rsp["events"], "create_denom", lambda attrs: "creator" in attrs
    )
    rsp = cli.query_tokenfactory_denoms(addr_a)
    denom = f"factory/{addr_a}/{subdenom}"
    erc20_address = denom_to_erc20_address(denom)
    expected = {
        "creator": addr_a,
        "new_token_denom": denom,
        "new_token_eth_addr": erc20_address,
    }
    assert expected.items() <= event.items()

    assert denom in rsp.get("denoms"), rsp
    pair = cli.query_erc20_token_pair(denom)
    assert pair == {
        "erc20_address": erc20_address,
        "denom": denom,
        "enabled": True,
        "contract_owner": "OWNER_EXTERNAL",
    }
    balance = cli.balance(addr_a, denom)
    amt = 10**6
    coin = f"{amt}{denom}"
    # check mint tokenfactory denom
    rsp = cli.mint_tokenfactory_denom(coin, _from=sender, gas=gas)
    assert rsp["code"] == 0, rsp["raw_log"]
    event = find_log_event_attrs(
        rsp["events"], "tf_mint", lambda attrs: "mint_to_address" in attrs
    )
    expected = {
        "mint_to_address": addr_a,
        "amount": coin,
    }
    assert expected.items() <= event.items()

    current = cli.balance(addr_a, denom)
    assert current == balance + amt
    balance = current
    # check transfer tokenfactory denom
    rsp = cli.transfer(addr_a, addr_b, f"{transfer_amt}{denom}")
    assert rsp["code"] == 0, rsp["raw_log"]
    current = cli.balance(addr_a, denom)
    assert current == balance - transfer_amt
    balance = current
    # check burn tokenfactory denom
    burn_amt = 10**3
    coin = f"{burn_amt}{denom}"
    rsp = cli.burn_tokenfactory_denom(coin, _from=sender, gas=gas)
    assert rsp["code"] == 0, rsp["raw_log"]
    event = find_log_event_attrs(
        rsp["events"], "tf_burn", lambda attrs: "burn_from_address" in attrs
    )
    expected = {
        "burn_from_address": addr_a,
        "amount": coin,
    }
    assert expected.items() <= event.items()

    current = cli.balance(addr_a, denom)
    assert current == balance - burn_amt
    balance = current
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
                "authority": eth_to_bech32(module_address("gov")),
                "sendEnabled": send_enable,
            }
        ],
    )
    assert cli.query_bank_send(*denoms) == send_enable
    rsp = cli.transfer(addr_a, addr_b, f"1{denom}")
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

import os
import time
from pathlib import Path

import pytest

from .utils import (
    assert_create_tokenfactory_denom,
    assert_mint_tokenfactory_denom,
    assert_set_tokenfactory_denom,
    assert_transfer,
    find_log_event_attrs,
    get_balance,
    wait_for_new_blocks,
)


def test_tokenfactory_admin(mantra, connect_mantra, tmp_path, need_prune=True):
    cli = connect_mantra.cosmos_cli(tmp_path)
    community = "community"
    signer2 = "signer2"
    cli.create_account(community, os.environ["COMMUNITY_MNEMONIC"])
    cli.create_account(signer2, os.environ["SIGNER2_MNEMONIC"])
    addr_a = cli.address(community)
    addr_b = cli.address(signer2)
    subdenom = f"admin{time.time()}"
    denom = assert_create_tokenfactory_denom(cli, subdenom, _from=addr_a, gas=620000)
    msg = "denom prefix is incorrect. Is: invalidfactory"
    with pytest.raises(AssertionError, match=msg):
        cli.query_denom_authority_metadata(f"invalid{denom}", _from=addr_a).get("Admin")

    assert_set_tokenfactory_denom(cli, tmp_path, denom, _from=addr_a)
    rsp = cli.update_tokenfactory_admin(denom, addr_b, _from=addr_a)
    assert rsp["code"] == 0, rsp["raw_log"]
    rsp = cli.query_denom_authority_metadata(denom, _from=addr_a).get("Admin")
    assert rsp == addr_b, rsp

    if need_prune:
        wait_for_new_blocks(cli, 5)
        mantra.supervisorctl("stop", "mantra-canary-net-1-node2")
        print(mantra.cosmos_cli(2).prune())
        mantra.supervisorctl("start", "mantra-canary-net-1-node2")

    amt = 10000
    if get_balance(cli, addr_b) < amt:
        assert_transfer(cli, addr_a, addr_b, amt=amt)
    rsp = cli.update_tokenfactory_admin(denom, addr_a, _from=addr_b)
    assert rsp["code"] == 0, rsp["raw_log"]
    wait_for_new_blocks(cli, 5)


@pytest.mark.connect
def test_connect_tokenfactory(connect_mantra, tmp_path):
    test_tokenfactory_admin(None, connect_mantra, tmp_path, need_prune=False)


def test_setup_hooks_denom(mantra):
    cli = mantra.cosmos_cli()
    community = "community"
    signer2 = "signer2"
    addr_a = cli.address(community)
    addr_b = cli.address(signer2)
    subdenom = f"admin{time.time()}"
    TRANSFER_CAP = 1000000
    amt = 10000000
    gas = 2500000
    denom = assert_create_tokenfactory_denom(cli, subdenom, _from=addr_a, gas=620000)
    assert_mint_tokenfactory_denom(cli, denom, amt, _from=addr_a, gas=gas)
    for name in ["transfer_cap", "track_before_send"]:
        contract = Path(__file__).parent / f"contracts/contracts/{name}.wasm"
        res = cli.wasm_store(
            str(contract),
            addr_a,
            _from=community,
            gas=gas,
        )
        assert res["code"] == 0
        attr = "code_id"
        code_id = find_log_event_attrs(
            res["events"], "store_code", lambda attrs: attr in attrs
        ).get(attr)

        res = cli.wasm_instantiate(code_id, community, _from=community, gas=gas)
        assert res["code"] == 0
        attr = "_contract_address"
        contract_address = find_log_event_attrs(
            res["events"], "instantiate", lambda attrs: attr in attrs
        ).get(attr)

        if name == "transfer_cap":
            res = cli.set_tokenfactory_before_send_hook(
                denom, contract_address, _from=addr_a
            )
            assert res["code"] == 0
            before = (
                cli.balance(addr_a, denom),
                cli.balance(addr_b, denom),
            )
            res = cli.transfer(addr_a, addr_b, f"{TRANSFER_CAP+1}{denom}")
            assert res["code"] != 0
            assert "Transfer amount exceeds the maximum" in res["raw_log"]
            res = cli.transfer(addr_a, addr_b, f"{TRANSFER_CAP}{denom}", gas=250000)
            assert res["code"] == 0
            after = (
                cli.balance(addr_a, denom),
                cli.balance(addr_b, denom),
            )
            assert after == (before[0] - TRANSFER_CAP, before[1] + TRANSFER_CAP)
        else:
            before = (
                cli.balance(addr_a, denom),
                cli.balance(contract_address, denom),
            )
            amt = 10
            res = cli.transfer(addr_a, contract_address, f"{amt}{denom}", gas=gas)
            res = cli.set_tokenfactory_before_send_hook(
                denom, contract_address, _from=addr_a
            )
            assert res["code"] == 0
            before = (
                cli.balance(addr_a, denom),
                cli.balance(contract_address, denom),
            )
            res = cli.transfer(addr_a, contract_address, f"{amt}{denom}", gas=gas)
            assert res["code"] == 0
            assert int(res["gas_used"]) > 700000
            after = (
                cli.balance(addr_a, denom),
                cli.balance(contract_address, denom),
            )
            assert after == (before[0] - amt, before[1] + amt)

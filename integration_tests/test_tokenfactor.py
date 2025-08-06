import json
import os
import time
from pathlib import Path

import pytest

from .utils import (
    DEFAULT_GAS,
    assert_create_tokenfactory_denom,
    assert_transfer,
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

    name = "Dubai"
    symbol = "DLD"
    meta = {
        "description": name,
        "denom_units": [{"denom": denom}, {"denom": symbol, "exponent": 6}],
        "base": denom,
        "display": symbol,
        "name": name,
        "symbol": symbol,
    }
    file_meta = Path(tmp_path) / "meta.json"
    file_meta.write_text(json.dumps(meta))
    rsp = cli.set_tokenfactory_denom(file_meta, _from=addr_a)
    assert rsp["code"] == 0, rsp["raw_log"]
    assert cli.query_bank_denom_metadata(denom) == meta

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

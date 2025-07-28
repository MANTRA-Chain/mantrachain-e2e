import json
import os
import time
from pathlib import Path

import pytest

from .utils import wait_for_new_blocks


def test_tokenfactory_admin(mantra, connect_mantra, tmp_path, need_prune=True):
    cli = connect_mantra.cosmos_cli(tmp_path)
    community = "community"
    signer2 = "signer2"
    cli.create_account(community, os.environ["COMMUNITY_MNEMONIC"])
    cli.create_account(signer2, os.environ["SIGNER2_MNEMONIC"])
    addr_a = cli.address(community)
    addr_b = cli.address(signer2)
    subdenom = f"admin{time.time()}"
    rsp = cli.create_tokenfactory_denom(subdenom, _from=addr_a, gas=620000)
    assert rsp["code"] == 0, rsp["raw_log"]
    rsp = cli.query_tokenfactory_denoms(addr_a)
    denom = f"factory/{addr_a}/{subdenom}"
    assert denom in rsp.get("denoms"), rsp
    rsp = cli.query_denom_authority_metadata(denom, _from=addr_a).get("Admin")
    assert rsp == addr_a, rsp
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
    assert cli.query_denom_metadata(denom) == meta

    rsp = cli.update_tokenfactory_admin(denom, addr_b, _from=addr_a)
    assert rsp["code"] == 0, rsp["raw_log"]
    rsp = cli.query_denom_authority_metadata(denom, _from=addr_a).get("Admin")
    assert rsp == addr_b, rsp

    if need_prune:
        wait_for_new_blocks(cli, 5)
        mantra.supervisorctl("stop", "mantra-canary-net-1-node2")
        print(mantra.cosmos_cli(2).prune())
        mantra.supervisorctl("start", "mantra-canary-net-1-node2")

    rsp = cli.update_tokenfactory_admin(denom, addr_a, _from=addr_b)
    assert rsp["code"] == 0, rsp["raw_log"]
    wait_for_new_blocks(cli, 5)


@pytest.mark.connect
def test_connect_tokenfactory(connect_mantra, tmp_path):
    test_tokenfactory_admin(None, connect_mantra, tmp_path, need_prune=False)

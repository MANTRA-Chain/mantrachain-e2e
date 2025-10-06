import json
import os
import time
from datetime import timedelta
from pathlib import Path

import pytest
import requests
import web3
from dateutil.parser import isoparse
from eth_account import Account
from eth_contract.contract import ContractFunction
from eth_utils import to_checksum_address
from pystarport import cluster

from .network import setup_custom_mantra
from .utils import (
    ACCOUNTS,
    DEFAULT_DENOM,
    WEI_PER_ETH,
    WEI_PER_UOM,
    BondStatus,
    find_log_event_attrs,
    wait_for_block,
    wait_for_block_time,
    wait_for_new_blocks,
)

DELEGATE = ContractFunction.from_abi("delegate(address,string,uint256)")
UNDELEGATE = ContractFunction.from_abi("undelegate(address,string,uint256)")
STAKING = to_checksum_address("0x0000000000000000000000000000000000000800")


pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def custom_mantra(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp("staking")
    yield from setup_custom_mantra(
        path,
        27200,
        Path(__file__).parent / "configs/staking.jsonnet",
        chain=chain,
    )


async def get_validators(w3):
    VALIDATORS = ContractFunction.from_abi(
        "validators(string,(bytes,uint64,uint64,bool,bool))((string,string,bool,uint8,uint256,uint256,string,int64,int64,uint256,uint256)[],(bytes,uint64))"  # noqa: E501
    )
    res, _ = await VALIDATORS(BondStatus.BONDED.value, [b"", 0, 10, False, False]).call(
        w3, to=STAKING
    )
    return res


async def test_staking_delegate(mantra):
    cli = mantra.cosmos_cli()
    w3 = mantra.async_w3
    name = "signer1"
    amt = 2
    acct = ACCOUNTS[name]
    bonded = cli.staking_pool()
    balance_bf = await w3.eth.get_balance(acct.address)
    res = await get_validators(w3)
    validator = cli.debug_addr(res[0][0], bech="val")
    res = await DELEGATE(acct.address, validator, amt).transact(
        w3, acct.address, to=STAKING
    )
    assert res.status == 1
    fee = res["gasUsed"] * res["effectiveGasPrice"]
    assert cli.staking_pool() == bonded + amt
    balance = await w3.eth.get_balance(acct.address)
    assert balance_bf == balance + amt * WEI_PER_UOM + fee


async def test_staking_unbond(mantra):
    cli = mantra.cosmos_cli()
    w3 = mantra.async_w3
    name = "signer1"
    acct = ACCOUNTS[name]
    res = await get_validators(w3)
    val_ops = [cli.debug_addr(validator[0], bech="val") for validator in res[:2]]
    balance_bf = await w3.eth.get_balance(acct.address)
    bonded_bf = cli.staking_pool()
    amounts = [3, 4]
    fee = 0

    for i, amt in enumerate(amounts):
        res = await DELEGATE(acct.address, val_ops[i], amt).transact(
            w3, acct.address, to=STAKING
        )
        assert res.status == 1
        fee += res["gasUsed"] * res["effectiveGasPrice"]

    assert cli.staking_pool() == bonded_bf + sum(amounts)
    balance = await w3.eth.get_balance(acct.address)
    assert balance == balance_bf - sum(amounts) * WEI_PER_UOM - fee

    unbonded_bf = cli.staking_pool(bonded=False)
    unbonded_amt = 2
    res = await UNDELEGATE(acct.address, val_ops[i], unbonded_amt).transact(
        w3, acct.address, to=STAKING
    )
    assert res.status == 1
    fee += res["gasUsed"] * res["effectiveGasPrice"]
    assert cli.staking_pool(bonded=False) == unbonded_bf + unbonded_amt
    blk = res["blockNumber"]
    rsp = requests.get(f"{cli.node_rpc_http}/block_results?height={blk}").json()
    rsp = next((tx for tx in rsp["result"]["txs_results"] if tx["code"] == 0), None)
    data = find_log_event_attrs(
        rsp["events"], "unbond", lambda attrs: "completion_time" in attrs
    )
    wait_for_block_time(cli, isoparse(data["completion_time"]) + timedelta(seconds=1))
    balance = await w3.eth.get_balance(acct.address)
    assert balance == balance_bf - (sum(amounts) - unbonded_amt) * WEI_PER_UOM - fee


async def test_staking_redelegate(mantra):
    cli = mantra.cosmos_cli()
    w3 = mantra.async_w3
    name = "signer1"
    acct = ACCOUNTS[name]
    res = await get_validators(w3)
    val_ops = [cli.debug_addr(validator[0], bech="val") for validator in res[:2]]
    amounts = [3, 4]
    fee = 0

    for i, amt in enumerate(amounts):
        res = await DELEGATE(acct.address, val_ops[i], amt).transact(
            w3, acct.address, to=STAKING
        )
        assert res.status == 1
        fee += res["gasUsed"] * res["effectiveGasPrice"]

    DELEGATION = ContractFunction.from_abi(
        "delegation(address,string)(uint256,(string,uint256))"
    )
    _, balance_bf = await DELEGATION(acct.address, val_ops[0]).call(w3, to=STAKING)
    redelegate_amt = 2
    REDELEGATE = ContractFunction.from_abi("redelegate(address,string,string,uint256)")
    res = await REDELEGATE(
        acct.address, val_ops[0], val_ops[1], redelegate_amt
    ).transact(w3, acct.address, to=STAKING)
    assert res.status == 1
    fee += res["gasUsed"] * res["effectiveGasPrice"]
    _, balance = await DELEGATION(acct.address, val_ops[0]).call(w3, to=STAKING)
    assert balance_bf[1] == balance[1] + redelegate_amt


async def test_join_validator(mantra):
    w3 = mantra.async_w3
    cli = mantra.cosmos_cli()
    mnemonic = os.getenv("VALIDATOR4_MNEMONIC")
    acct = Account.from_mnemonic(mnemonic)
    data = Path(mantra.base_dir).parent
    chain_id = mantra.config["chain_id"]
    clustercli = cluster.ClusterCLI(data, cmd="mantrachaind", chain_id=chain_id)
    moniker = "new joined"
    node_index = clustercli.create_node(moniker=moniker, mnemonic=mnemonic)
    cli = clustercli.cosmos_cli(node_index)
    cli0 = mantra.cosmos_cli()
    staked = 10_000_000_000_000_000_000
    fund = f"{staked + 1_000_000}{DEFAULT_DENOM}"
    val_addr = cli.address("validator", bech="val")
    addr = cli.address("validator")

    res = cli0.transfer(cli0.address("community"), addr, fund)
    assert res["code"] == 0, res
    # Modify the json-rpc addresses to avoid conflict
    cluster.edit_app_cfg(
        clustercli.home(node_index) / "config/app.toml",
        clustercli.base_port(node_index),
        {
            "json-rpc": {
                "enable": True,
                "address": "127.0.0.1:{EVMRPC_PORT}",
                "ws-address": "127.0.0.1:{EVMRPC_PORT_WS}",
            }
        },
    )
    clustercli.supervisor.startProcess(f"{chain_id}-node{node_index}")
    wait_for_block(cli, cli0.block_height() + 1)
    time.sleep(1)
    wait_for_block(cli, cli.block_height())

    count = len(cli.validators())
    pubkey = (
        cli.raw(
            "comet",
            "show-validator",
            home=cli.data_dir,
        )
        .strip()
        .decode()
    )
    pubkey = json.loads(pubkey)["key"]
    desc = [moniker, "identity", "website", "securityContact", "details"]
    commission = [
        int(0.1 * WEI_PER_ETH),
        int(0.2 * WEI_PER_ETH),
        int(0.01 * WEI_PER_ETH),
    ]
    min_self_delegation = 1
    CREATE_VALIDATOR = ContractFunction.from_abi(
        "createValidator((string,string,string,string,string),(uint256,uint256,uint256),uint256,address,string,uint256)"  # noqa: E501
    )
    res = await CREATE_VALIDATOR(
        desc, commission, min_self_delegation, acct.address, pubkey, staked
    ).transact(w3, acct, to=STAKING, gas=200_000)
    assert res.status == 1

    time.sleep(2)
    assert len(cli.validators()) == count + 1

    val = cli.validator(val_addr)
    assert not val.get("jailed")
    assert val["status"] == BondStatus.BONDED.value
    assert val["tokens"] == str(staked)
    assert val["description"]["moniker"] == moniker
    assert val["commission"]["commission_rates"] == {
        "rate": "0.100000000000000000",
        "max_rate": "0.200000000000000000",
        "max_change_rate": "0.010000000000000000",
    }

    EDIT_VALIDATOR = ContractFunction.from_abi(
        "editValidator((string,string,string,string,string),address,int256,int256)"
    )
    msg = "commission cannot be changed more than once in 24h"
    with pytest.raises(web3.exceptions.ContractLogicError, match=msg):
        await EDIT_VALIDATOR(
            desc, acct.address, commission[0] * 2, min_self_delegation
        ).transact(w3, acct, to=STAKING)

    desc[0] = "awesome node"
    res = await EDIT_VALIDATOR(desc, acct.address, -1, -1).transact(
        w3, acct, to=STAKING
    )
    assert res.status == 1
    assert cli.validator(val_addr)["description"]["moniker"] == "awesome node"


async def test_min_self_delegation(custom_mantra):
    mnemonic = os.getenv("VALIDATOR4_MNEMONIC")
    acct = Account.from_mnemonic(mnemonic)
    cli = custom_mantra.cosmos_cli(i=3)
    w3 = custom_mantra.async_w3
    val = cli.address("validator", bech="val")
    amt = 9_000_000_000_000_000_000
    gas = 400_000
    res = await UNDELEGATE(acct.address, val, amt).transact(
        w3, acct, to=STAKING, gas=gas
    )
    assert res.status == 1
    assert cli.validator(val).get("status") == BondStatus.BONDED.value
    amt = 1
    res = await UNDELEGATE(acct.address, val, amt).transact(
        w3, acct, to=STAKING, gas=gas
    )
    assert res.status == 1
    wait_for_new_blocks(cli, 2)
    assert cli.validator(val).get("status") == BondStatus.UNBONDING.value

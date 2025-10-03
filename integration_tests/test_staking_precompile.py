from datetime import timedelta

import pytest
import requests
from dateutil.parser import isoparse
from eth_contract.contract import ContractFunction
from eth_utils import to_checksum_address

from .utils import (
    ACCOUNTS,
    WEI_PER_UOM,
    find_log_event_attrs,
    wait_for_block_time,
)

DELEGATE = ContractFunction.from_abi("delegate(address,string,uint256)(bool)")
DELEGATION = ContractFunction.from_abi(
    "delegation(address,string)(uint256,(string,uint256))"
)
UNDELEGATE = ContractFunction.from_abi("undelegate(address,string,uint256)(int64)")
REDELEGATE = ContractFunction.from_abi(
    "redelegate(address,string,string,uint256)(int64)"
)
STAKING = to_checksum_address("0x0000000000000000000000000000000000000800")

pytestmark = pytest.mark.asyncio


async def test_staking_delegate(mantra):
    cli = mantra.cosmos_cli()
    name = "signer1"
    amt = 2
    acct = ACCOUNTS[name]
    bonded = cli.staking_pool()
    w3 = mantra.async_w3
    balance_bf = await w3.eth.get_balance(acct.address)
    validator = cli.validators()[0]["operator_address"]
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
    name = "signer1"
    acct = ACCOUNTS[name]
    val_ops = [v["operator_address"] for v in cli.validators()[:2]]
    w3 = mantra.async_w3
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
    name = "signer1"
    acct = ACCOUNTS[name]
    val_ops = [v["operator_address"] for v in cli.validators()[:2]]
    w3 = mantra.async_w3
    amounts = [3, 4]
    fee = 0

    for i, amt in enumerate(amounts):
        res = await DELEGATE(acct.address, val_ops[i], amt).transact(
            w3, acct.address, to=STAKING
        )
        assert res.status == 1
        fee += res["gasUsed"] * res["effectiveGasPrice"]

    _, balance_bf = await DELEGATION(acct.address, val_ops[0]).call(w3, to=STAKING)
    redelegate_amt = 2
    res = await REDELEGATE(
        acct.address, val_ops[0], val_ops[1], redelegate_amt
    ).transact(w3, acct.address, to=STAKING)
    assert res.status == 1
    fee += res["gasUsed"] * res["effectiveGasPrice"]
    _, balance = await DELEGATION(acct.address, val_ops[0]).call(w3, to=STAKING)
    assert balance_bf[1] == balance[1] + redelegate_amt

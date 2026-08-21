import asyncio
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
from eth_contract.contract import Contract
from eth_contract.deploy_utils import (
    ensure_create2_deployed,
    ensure_deployed_by_create2,
)
from eth_contract.utils import get_initcode, sign_transaction
from pystarport import cluster
from pystarport.utils import (
    BondStatus,
    wait_for_block,
    wait_for_block_time,
    wait_for_new_blocks,
)
from web3.exceptions import TransactionNotFound

from .network import setup_custom_mantra
from .utils import (
    ACCOUNTS,
    CMD,
    DEFAULT_DENOM,
    WEI_PER_DENOM,
    WEI_PER_ETH,
    address_to_bytes32,
    assert_estimate_covers_receipt,
    assert_gas_estimate_within_floor,
    bech32_to_eth,
    build_contract,
    duration,
    edit_app_cfg,
    eth_to_bech32,
    find_log_event_attrs,
    module_address,
    wait_for_eth_tx_result,
)

PRECOMPILE = Contract(build_contract("StakingI")["abi"])
DELEGATE = PRECOMPILE.fns.delegate
UNDELEGATE = PRECOMPILE.fns.undelegate
VALIDATOR = PRECOMPILE.fns.validator
STAKING = "0x0000000000000000000000000000000000000800"
TEST_STAKING = Contract(build_contract("TestStaking")["abi"])
TEST_STAKING_CONTRACT = None
EXPLOIT = Contract(build_contract("StakingExploit")["abi"])
EXPLOIT_CONTRACT = None
gas = 400_000


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
    params = [b"", 0, 10, False, False]
    res, _ = await PRECOMPILE.fns.validators(BondStatus.BONDED.value, params).call(
        w3, to=STAKING
    )
    return res


@pytest.mark.connect
async def test_connect_staking_delegate(connect_mantra, tmp_path):
    await test_staking_delegate(None, connect_mantra, tmp_path)


async def get_test_staking_contract(w3):
    global TEST_STAKING_CONTRACT
    signer = ACCOUNTS["community"]
    if TEST_STAKING_CONTRACT is None:
        artifact = build_contract("TestStaking")
        await ensure_create2_deployed(w3, signer)
        TEST_STAKING_CONTRACT = await ensure_deployed_by_create2(
            w3,
            signer,
            get_initcode(artifact),
            salt=100,
        )
    return TEST_STAKING_CONTRACT


async def get_exploit_contract(w3):
    global EXPLOIT_CONTRACT
    signer = ACCOUNTS["community"]
    if EXPLOIT_CONTRACT is None:
        artifact = build_contract("StakingExploit")
        await ensure_create2_deployed(w3, signer)
        EXPLOIT_CONTRACT = await ensure_deployed_by_create2(
            w3,
            signer,
            get_initcode(artifact),
            salt=101,
        )
    return EXPLOIT_CONTRACT


async def delegated_amount(w3, delegator, validator):
    """delegator's bonded amount to validator, 0 if there is no delegation."""
    try:
        _, balance = await PRECOMPILE.fns.delegation(delegator, validator).call(
            w3, to=STAKING
        )
    except Exception:
        return 0
    return balance[1]


async def test_delegate_transfer_to_bonded_pool_rejected(mantra):
    """Pool-drain exploit rejected by the SetBalance guard.

    Delegating via precompile moves msg.value into blocked bonded tokens pool
    (which BalanceHandler skips syncing), a following raw transfer to it caches
    a stale balance that would clobber the real bank balance on commit.
    evm 3524ebc6 rejects the tx ("is not allowed to receive funds"), and it's
    dropped from block RPCs (cosmos/evm#1107) so eth_getTransaction cannot find it.
    """
    cli = mantra.cosmos_cli()
    w3 = mantra.async_w3
    acct = ACCOUNTS["community"]
    exploit = await get_exploit_contract(w3)

    validator = cli.debug_addr((await get_validators(w3))[0][0], bech="val")
    pool_bech32 = module_address("bonded_tokens_pool")
    pool_eth = bech32_to_eth(pool_bech32)

    # prefund the contract for the raw transfer on top of the delegated msg.value
    receipt = await w3.eth.wait_for_transaction_receipt(
        await send_value(w3, acct, exploit, 1_000_000)
    )
    assert receipt["status"] == 1

    amt = 100  # delegated msg.value; > 15 so the clobbered amount differs
    pool_before = cli.staking_pool()
    deleg_before = await delegated_amount(w3, exploit, validator)
    contract_before = await w3.eth.get_balance(exploit)

    fn = EXPLOIT.fns.delegateWithTransfer(pool_eth, validator, amt)
    height = cli.block_height()
    tx_hash = await send_value(
        w3, acct, exploit, amt * WEI_PER_DENOM, data=fn.data, gas=3_000_000
    )

    # admitted and included, but fails when the statedb is committed
    res = await wait_for_eth_tx_result(cli, w3, tx_hash, height)
    assert res["code"] != 0, res
    assert f"{pool_bech32} is not allowed to receive funds" in res["log"], res["log"]
    with pytest.raises(TransactionNotFound):
        await w3.eth.get_transaction(tx_hash)

    # no pool funds burned, no phantom delegation: the drain never gets going
    assert cli.staking_pool() == pool_before
    assert await delegated_amount(w3, exploit, validator) == deleg_before
    assert await w3.eth.get_balance(exploit) == contract_before


async def send_value(w3, acct, to, value, data=b"", gas=30000):
    latest = await w3.eth.get_block("latest")
    base_fee = int(latest.get("baseFeePerGas") or 0)
    tip = int(await w3.eth.max_priority_fee)
    signed = await sign_transaction(
        w3,
        acct,
        to=to,
        value=value,
        data=data,
        gas=gas,
        maxFeePerGas=(base_fee + tip) * 2 + 1,
        maxPriorityFeePerGas=tip,
        nonce=await w3.eth.get_transaction_count(acct.address),
    )
    return await w3.eth.send_raw_transaction(signed.raw_transaction)


async def delegate(w3, acct, validator, amt, to):
    if to == STAKING:
        return await DELEGATE(acct.address, validator, amt).transact(
            w3, acct, to=to, gas=gas
        )
    return await TEST_STAKING.fns.callDelegate(validator, amt).transact(
        w3, acct, to=to, gas=gas, value=amt * WEI_PER_DENOM
    )


async def undelegate(w3, acct, validator, amt, to):
    if to == STAKING:
        return await UNDELEGATE(acct.address, validator, amt).transact(
            w3, acct, to=to, gas=gas
        )
    return await TEST_STAKING.fns.callUndelegate(validator, amt).transact(
        w3, acct, to=to, gas=gas
    )


async def redelegate(w3, acct, val_ops, amt, to):
    if to == STAKING:
        return await PRECOMPILE.fns.redelegate(
            acct.address, val_ops[0], val_ops[1], amt
        ).transact(w3, acct, to=to, gas=gas)
    else:
        return await TEST_STAKING.fns.callRedelegate(
            val_ops[0], val_ops[1], amt
        ).transact(w3, acct, to=to, gas=gas)


async def test_staking_delegate(mantra, connect_mantra, tmp_path):
    cli = connect_mantra.cosmos_cli(tmp_path)
    w3 = connect_mantra.async_w3
    test_staking = await get_test_staking_contract(w3)
    amt = 2
    name = "signer1"
    acct = ACCOUNTS[name]
    addr = (await get_validators(w3))[0][0]
    validator = cli.debug_addr(addr, bech="val")

    for to, caller in [
        (STAKING, acct.address),
        (test_staking, test_staking),
    ]:
        bonded = cli.staking_pool()
        balance_before = await w3.eth.get_balance(acct.address)
        res = await delegate(w3, acct, validator, amt, to=to)
        assert res.status == 1
        assert res.logs[0].topics == [
            PRECOMPILE.events.Delegate.topic,
            address_to_bytes32(caller),
            address_to_bytes32(addr),
        ]
        fee = res["gasUsed"] * res["effectiveGasPrice"]
        assert cli.staking_pool() == bonded + amt
        balance_after = await w3.eth.get_balance(acct.address)
        assert balance_before == balance_after + amt * WEI_PER_DENOM + fee


@pytest.mark.connect
async def test_connect_staking_unbond(connect_mantra, tmp_path):
    await test_staking_unbond(None, connect_mantra, tmp_path)


async def test_staking_unbond(mantra, connect_mantra, tmp_path):
    cli = connect_mantra.cosmos_cli(tmp_path)
    unbond_duration = duration(cli.get_params("staking")["unbonding_time"])
    if unbond_duration > 60:
        pytest.skip(f"unbond_duration is {unbond_duration} too long for test")
    w3 = connect_mantra.async_w3
    test_staking = await get_test_staking_contract(w3)
    name = "signer1"
    acct = ACCOUNTS[name]
    res = await get_validators(w3)
    val_ops = [cli.debug_addr(validator[0], bech="val") for validator in res[:2]]
    amounts = [3, 4]
    fee = 0

    for to in [STAKING, test_staking]:
        for i, amt in enumerate(amounts):
            balance_bf = await w3.eth.get_balance(acct.address)
            bonded_bf = cli.staking_pool()
            res = await delegate(w3, acct, val_ops[i], amt, to=to)
            assert res.status == 1
            fee = res["gasUsed"] * res["effectiveGasPrice"]
            assert cli.staking_pool() == bonded_bf + amt
            balance = await w3.eth.get_balance(acct.address)
            assert balance == balance_bf - amt * WEI_PER_DENOM - fee

    unbonded_bf = cli.staking_pool(bonded=False)
    unbond_amt = 2

    for to, caller in [
        (STAKING, acct.address),
        (test_staking, test_staking),
    ]:
        balance_user_bf = await w3.eth.get_balance(acct.address)
        balance_contract_bf = await w3.eth.get_balance(test_staking)
        res = await undelegate(w3, acct, val_ops[0], unbond_amt, to=to)
        assert res.status == 1
        assert res.logs[0].topics == [
            PRECOMPILE.events.Unbond.topic,
            address_to_bytes32(caller),
            address_to_bytes32(cli.debug_addr(val_ops[0], bech="hex")),
        ]
        fee = res["gasUsed"] * res["effectiveGasPrice"]
        assert cli.staking_pool(bonded=False) == unbonded_bf + unbond_amt
        blk = res["blockNumber"]
        rsp = requests.get(f"{cli.node_rpc_http}/block_results?height={blk}").json()
        rsp = next((tx for tx in rsp["result"]["txs_results"] if tx["code"] == 0), None)
        data = find_log_event_attrs(
            rsp["events"], "unbond", lambda attrs: "completion_time" in attrs
        )
        wait_for_block_time(
            cli, isoparse(data["completion_time"]) + timedelta(seconds=1)
        )
        balance_user_af = await w3.eth.get_balance(acct.address)
        balance_contract_af = await w3.eth.get_balance(test_staking)
        unbond_diff = unbond_amt * WEI_PER_DENOM
        if to == STAKING:
            assert balance_user_af == balance_user_bf - fee + unbond_diff
        else:
            assert balance_user_af == balance_user_bf - fee
            assert balance_contract_af == balance_contract_bf + unbond_diff


async def test_staking_redelegate(mantra, connect_mantra, tmp_path):
    cli = connect_mantra.cosmos_cli(tmp_path)
    w3 = connect_mantra.async_w3
    test_staking = await get_test_staking_contract(w3)
    name = "signer1"
    acct = ACCOUNTS[name]
    res = await get_validators(w3)
    val_ops = [cli.debug_addr(validator[0], bech="val") for validator in res[:2]]
    amounts = [3, 4]
    fee = 0

    for to in [STAKING, test_staking]:
        for i, amt in enumerate(amounts):
            balance_bf = await w3.eth.get_balance(acct.address)
            bonded_bf = cli.staking_pool()
            res = await delegate(w3, acct, val_ops[i], amt, to=to)
            assert res.status == 1
            fee = res["gasUsed"] * res["effectiveGasPrice"]
            assert cli.staking_pool() == bonded_bf + amt
            balance = await w3.eth.get_balance(acct.address)
            assert balance == balance_bf - amt * WEI_PER_DENOM - fee

    DELEGATION = PRECOMPILE.fns.delegation
    redelegate_amt = 2

    for to, caller in [
        (STAKING, acct.address),
        (test_staking, test_staking),
    ]:
        _, balance_bf = await DELEGATION(caller, val_ops[0]).call(w3, to=STAKING)
        res = await redelegate(w3, acct, val_ops, redelegate_amt, to=to)
        assert res.status == 1
        assert res.logs[0].topics == [
            PRECOMPILE.events.Redelegate.topic,
            address_to_bytes32(caller),
            address_to_bytes32(cli.debug_addr(val_ops[0], bech="hex")),
            address_to_bytes32(cli.debug_addr(val_ops[1], bech="hex")),
        ]
        _, balance = await DELEGATION(caller, val_ops[0]).call(w3, to=STAKING)
        assert balance_bf[1] == balance[1] + redelegate_amt


async def test_staking_delegate_from_vesting(mantra):
    cli = mantra.cosmos_cli()
    w3 = mantra.async_w3

    # brand-new account: create-vesting-account rejects existing accounts
    vester = Account.create()
    vester_acc = eth_to_bech32(vester.address)
    funder = cli.address("community")
    locked, spendable, del_amt = 2 * 10**18, 8 * 10**18, 10**18

    # fund `locked` (all locked as original vesting) + `spendable` extra
    end_time = int(time.time()) + 365 * 24 * 3600
    rsp = cli.create_periodic_vesting_acct(
        vester_acc, f"{locked}{DEFAULT_DENOM}", end_time, from_=funder
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    rsp = cli.transfer(funder, vester_acc, f"{spendable}{DEFAULT_DENOM}")
    assert rsp["code"] == 0, rsp["raw_log"]

    pre_bank = cli.balance(vester_acc, DEFAULT_DENOM)
    assert pre_bank == locked + spendable, pre_bank

    # delegate within both spendable and locked via the staking precompile
    validator = cli.debug_addr((await get_validators(w3))[0][0], bech="val")
    res = await DELEGATE(vester.address, validator, del_amt).transact(
        w3, vester, to=STAKING, gas=gas
    )
    assert res.status == 1

    gas_fee = res["gasUsed"] * res["effectiveGasPrice"] // WEI_PER_DENOM
    post_bank = cli.balance(vester_acc, DEFAULT_DENOM)
    # bank balance drops by exactly delegation + gas, no spurious mint/burn
    assert pre_bank - post_bank == del_amt + gas_fee, (pre_bank, post_bank, gas_fee)

    # vesting structure preserved: OV unchanged, delegation tracked as vesting
    bva = cli.account(vester_acc)["account"]["value"]["base_vesting_account"]
    assert bva["original_vesting"] == [{"denom": DEFAULT_DENOM, "amount": str(locked)}]
    assert bva["delegated_vesting"] == [
        {"denom": DEFAULT_DENOM, "amount": str(del_amt)}
    ]


async def test_join_validator(mantra):
    w3 = mantra.async_w3
    mnemonic = os.getenv("VALIDATOR4_MNEMONIC")
    acct = Account.from_mnemonic(mnemonic)
    data = Path(mantra.base_dir).parent
    chain_id = mantra.config["chain_id"]
    clustercli = cluster.ClusterCLI(data, cmd=CMD, chain_id=chain_id)
    moniker = "new joined"
    node_index = clustercli.create_node(moniker=moniker, mnemonic=mnemonic)
    cli = clustercli.cosmos_cli(node_index)
    cli0 = mantra.cosmos_cli()
    staked = 10_000_000_000_000_000_000
    fund = f"{staked + 1_000_000_000_000_000_000//WEI_PER_DENOM}{DEFAULT_DENOM}"
    val_addr = cli.address("validator", bech="val")
    addr = cli0.debug_addr(val_addr, bech="hex")

    res = cli0.transfer(cli0.address("community"), cli.address("validator"), fund)
    assert res["code"] == 0, res
    edit_app_cfg(clustercli, node_index)
    clustercli.supervisor.startProcess(f"{chain_id}-node{node_index}")
    wait_for_block(cli, cli0.block_height() + 1)
    await asyncio.sleep(0.5)
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
    res = await PRECOMPILE.fns.createValidator(
        desc, commission, min_self_delegation, acct.address, pubkey, staked
    ).transact(w3, acct, to=STAKING, gas=gas)
    assert res.status == 1
    assert res.logs[0].topics == [
        PRECOMPILE.events.CreateValidator.topic,
        address_to_bytes32(addr),
    ]
    await asyncio.sleep(2)
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

    EDIT_VALIDATOR = PRECOMPILE.fns.editValidator
    msg = "commission cannot be changed more than once in 24h"
    with pytest.raises(web3.exceptions.ContractLogicError, match=msg):
        await EDIT_VALIDATOR(
            desc, acct.address, commission[0] * 2, min_self_delegation
        ).transact(w3, acct, to=STAKING)

    desc[0] = "awesome node"
    res = await EDIT_VALIDATOR(desc, acct.address, -1, -1).transact(
        w3, acct, to=STAKING, gas=gas
    )
    assert res.status == 1
    assert res.logs[0].topics == [
        PRECOMPILE.events.EditValidator.topic,
        address_to_bytes32(addr),
    ]
    assert cli.validator(val_addr)["description"]["moniker"] == "awesome node"


async def test_min_self_delegation(custom_mantra):
    mnemonic = os.getenv("VALIDATOR4_MNEMONIC")
    acct = Account.from_mnemonic(mnemonic)
    cli = custom_mantra.cosmos_cli(i=3)
    w3 = custom_mantra.async_w3
    addr = bech32_to_eth(cli.address("validator"))
    val = cli.address("validator", bech="val")
    amt = 9_000_000_000_000_000_000
    res = await UNDELEGATE(acct.address, val, amt).transact(
        w3, acct, to=STAKING, gas=gas
    )
    assert res.status == 1
    res = await VALIDATOR(addr).call(w3, to=STAKING)
    assert res[3] == BondStatus.BONDED.to_int()
    amt = 1
    res = await UNDELEGATE(acct.address, val, amt).transact(
        w3, acct, to=STAKING, gas=gas
    )
    assert res.status == 1
    assert res.logs[0].topics == [
        PRECOMPILE.events.Unbond.topic,
        address_to_bytes32(acct.address),
        address_to_bytes32(addr),
    ]
    wait_for_new_blocks(cli, 2)
    res = await VALIDATOR(addr).call(w3, to=STAKING)
    assert res[3] == BondStatus.UNBONDING.to_int()


async def test_staking_eth_estimate_gas_matches_eth_call(mantra):
    """Check eth_estimateGas matches receipt gas_used for staking precompile call."""
    cli = mantra.cosmos_cli()
    w3 = mantra.async_w3
    val_bz = (await get_validators(w3))[0][0]
    validator = cli.debug_addr(val_bz, bech="val")
    delegator = ACCOUNTS["community"]

    call = DELEGATE(delegator.address, validator, 1)
    tx = {"to": STAKING, "from": delegator.address, "data": call.data}

    # Estimate + floor check BEFORE broadcast — delegate writes state, and
    # keeping both calls pinned to the same pre-broadcast block makes the
    # comparison deterministic.
    estimated = await assert_gas_estimate_within_floor(w3, tx)

    receipt = await DELEGATE(delegator.address, validator, 1).transact(
        w3, delegator, to=STAKING, gas=gas
    )
    assert_estimate_covers_receipt(estimated, int(receipt["gasUsed"]))

import asyncio
import json
from pathlib import Path

import pytest
from eth_account import Account
from eth_contract.contract import Contract, ContractFunction
from eth_contract.create2 import create2_address
from eth_contract.deploy_utils import (
    ensure_create2_deployed,
    ensure_createx_deployed,
    ensure_deployed_by_create2,
    ensure_deployed_by_create3,
    ensure_history_storage_deployed,
    ensure_multicall3_deployed,
)
from eth_contract.erc20 import ERC20
from eth_contract.history_storage import HISTORY_STORAGE_ADDRESS
from eth_contract.multicall3 import (
    MULTICALL3,
    MULTICALL3_ADDRESS,
    Call3Value,
    multicall,
)
from eth_contract.utils import ZERO_ADDRESS, balance_of, get_initcode, send_transaction
from eth_contract.weth import WETH
from web3 import AsyncWeb3
from web3.types import TxParams

from .utils import (
    ACCOUNTS,
    ADDRS,
    CONTRACTS,
    KEYS,
    WETH9_ARTIFACT,
    WETH_ADDRESS,
    WETH_SALT,
    address_to_bytes32,
    build_deploy_contract_async,
    deploy_contract_async,
    w3_wait_for_new_blocks_async,
)

pytestmark = pytest.mark.asyncio


MockERC20_ARTIFACT = json.loads(
    Path(__file__).parent.joinpath("contracts/contracts/MockERC20.json").read_text()
)

MULTICALL3ROUTER_ARTIFACT = json.loads(
    Path(__file__)
    .parent.joinpath("contracts/contracts/Multicall3Router.json")
    .read_text()
)
MULTICALL3ROUTER = create2_address(
    get_initcode(MULTICALL3ROUTER_ARTIFACT, MULTICALL3_ADDRESS)
)


async def assert_contract_deployed(w3):
    account = Account.from_key(KEYS["community"])
    await ensure_create2_deployed(w3, account)
    await ensure_multicall3_deployed(w3, account)
    await ensure_deployed_by_create2(
        w3,
        account,
        get_initcode(WETH9_ARTIFACT),
        salt=WETH_SALT,
    )
    assert MULTICALL3ROUTER == await ensure_deployed_by_create2(
        w3,
        account,
        get_initcode(MULTICALL3ROUTER_ARTIFACT, MULTICALL3_ADDRESS),
    )
    assert await w3.eth.get_code(WETH_ADDRESS)
    assert await w3.eth.get_code(MULTICALL3ROUTER)
    assert await w3.eth.get_code(MULTICALL3_ADDRESS)


@pytest.mark.connect
async def test_connect_flow(connect_mantra):
    await test_flow(None, connect_mantra)


async def test_flow(mantra, connect_mantra):
    w3 = connect_mantra.async_w3
    await assert_contract_deployed(w3)
    key = KEYS["community"]
    account = Account.from_key(KEYS["community"])
    await ensure_createx_deployed(w3, account)
    await ensure_history_storage_deployed(w3, account)
    assert await w3.eth.get_code(HISTORY_STORAGE_ADDRESS)
    contract = await deploy_contract_async(
        w3, CONTRACTS["TestBlockTxProperties"], key=key
    )
    height = await w3.eth.block_number
    await w3_wait_for_new_blocks_async(w3, 1)
    res = (await contract.caller.getBlockHash(height)).hex()
    blk = await w3.eth.get_block(height)
    assert res == blk.hash.hex(), res

    owner = account.address
    # test_create2_deploy
    initcode = get_initcode(MockERC20_ARTIFACT, "TEST", "TEST", 18)
    salt = 100
    token = await ensure_deployed_by_create2(w3, account, initcode, salt=salt)
    assert token == "0x854d811d90C6E81B84b29C1d7ed957843cF87bba"
    balance = await ERC20.fns.balanceOf(owner).call(w3, to=token)
    amt = 1000
    await ERC20.fns.mint(owner, amt).transact(w3, account, to=token)
    assert await ERC20.fns.balanceOf(owner).call(w3, to=token) == balance + amt

    # test_create3_deploy
    salt = 200
    token = await ensure_deployed_by_create3(w3, account, initcode, salt=salt)
    assert token == "0x60f7B32B5799838a480572Aee2A8F0355f607b38"
    balance = await ERC20.fns.balanceOf(owner).call(w3, to=token)
    await ERC20.fns.mint(owner, 1000).transact(w3, account, to=token)
    assert await ERC20.fns.balanceOf(owner).call(w3, to=token) == balance + amt

    # test_weth
    weth = WETH(to=WETH_ADDRESS)
    before = await balance_of(w3, ZERO_ADDRESS, owner)
    receipt = await weth.fns.deposit().transact(w3, account, value=1000)
    fee = receipt["effectiveGasPrice"] * receipt["gasUsed"]
    await balance_of(w3, WETH_ADDRESS, owner) == 1000
    receipt = await weth.fns.withdraw(1000).transact(w3, account)
    fee += receipt["effectiveGasPrice"] * receipt["gasUsed"]
    await balance_of(w3, WETH_ADDRESS, owner) == 0
    assert await balance_of(w3, ZERO_ADDRESS, owner) == before - fee

    # test_batch_call
    users = [Account.from_key(KEYS[key]) for key in ["community", "signer1", "signer2"]]
    amount = 1000
    amount_all = amount * len(users)

    balances = [(WETH_ADDRESS, ERC20.fns.balanceOf(user.address)) for user in users]
    balances_bf = await multicall(w3, balances)
    await MULTICALL3.fns.aggregate3Value(
        [Call3Value(WETH_ADDRESS, False, amount_all, weth.fns.deposit().data)]
        + [
            Call3Value(
                WETH_ADDRESS, False, 0, ERC20.fns.transfer(user.address, amount).data
            )
            for user in users
        ]
    ).transact(w3, users[0], value=amount_all)
    balances_af = await multicall(w3, balances)
    assert all(af - bf == amount for af, bf in zip(balances_af, balances_bf))

    for user in users:
        await ERC20.fns.approve(MULTICALL3_ADDRESS, amount).transact(
            w3, user, to=WETH_ADDRESS
        )

    await MULTICALL3.fns.aggregate3Value(
        [
            Call3Value(
                WETH_ADDRESS,
                data=ERC20.fns.transferFrom(
                    user.address, MULTICALL3_ADDRESS, amount
                ).data,
            )
            for user in users
        ]
        + [
            Call3Value(
                WETH_ADDRESS,
                data=weth.fns.transferFrom(
                    MULTICALL3_ADDRESS, users[0].address, amount_all
                ).data,
            ),
        ]
    ).transact(w3, users[0])
    await weth.fns.withdraw(amount_all).transact(w3, users[0], to=WETH_ADDRESS)
    balances_bf = await multicall(w3, balances)
    await balance_of(w3, WETH_ADDRESS, MULTICALL3_ADDRESS) == 0

    # test_multicall3_router
    amount_all = amount * len(users)
    router = Contract(MULTICALL3ROUTER_ARTIFACT["abi"])
    multicall3 = MULTICALL3ROUTER

    balances = [(WETH_ADDRESS, ERC20.fns.balanceOf(user.address)) for user in users]
    balances_bf = await multicall(w3, balances)
    assert (await multicall(w3, balances)) == balances_bf
    before = await balance_of(w3, ZERO_ADDRESS, users[0].address)

    # convert amount_all into WETH and distribute to users
    receipt = await MULTICALL3.fns.aggregate3Value(
        [Call3Value(WETH_ADDRESS, False, amount_all, WETH.fns.deposit().data)]
        + [
            Call3Value(
                WETH_ADDRESS, False, 0, ERC20.fns.transfer(user.address, amount).data
            )
            for user in users
        ]
    ).transact(w3, users[0], to=multicall3, value=amount_all)
    before -= receipt["effectiveGasPrice"] * receipt["gasUsed"]
    # check users's weth balances
    balances_af = await multicall(w3, balances)
    assert all(af - bf == amount for af, bf in zip(balances_af, balances_bf))
    balances_bf = balances_af

    # approve multicall3 to transfer WETH on behalf of users
    for i, user in enumerate(users):
        receipt = await ERC20.fns.approve(multicall3, amount).transact(
            w3, user, to=WETH_ADDRESS
        )
        if i == 0:
            before -= receipt["effectiveGasPrice"] * receipt["gasUsed"]

    # transfer WETH from all users to multicall3, withdraw it,
    # and send back to users[0]
    receipt = await MULTICALL3.fns.aggregate3Value(
        [
            Call3Value(
                WETH_ADDRESS,
                data=ERC20.fns.transferFrom(user.address, multicall3, amount).data,
            )
            for user in users
        ]
        + [
            Call3Value(WETH_ADDRESS, data=WETH.fns.withdraw(amount_all).data),
            Call3Value(
                multicall3,
                data=router.fns.sellToPool(
                    ZERO_ADDRESS, 10000, users[0].address, 0, b""
                ).data,
            ),
        ]
    ).transact(w3, users[0], to=multicall3)
    before -= receipt["effectiveGasPrice"] * receipt["gasUsed"]
    balances_af = await multicall(w3, balances)
    assert all(af + amount == bf for af, bf in zip(balances_af, balances_bf))
    assert await balance_of(w3, WETH_ADDRESS, multicall3) == 0
    assert await balance_of(w3, ZERO_ADDRESS, multicall3) == 0

    # user get all funds back other than gas fees
    assert await balance_of(w3, ZERO_ADDRESS, users[0].address) == before


async def test_7702(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    await assert_contract_deployed(w3)

    acct = ACCOUNTS["validator"]
    sponsor = ACCOUNTS["community"]
    multicall3 = MULTICALL3ROUTER

    nonce = await w3.eth.get_transaction_count(acct.address)
    chain_id = await w3.eth.chain_id
    auth = acct.sign_authorization(
        {"chainId": chain_id, "address": multicall3, "nonce": nonce}
    )
    amount = 1000
    calls = [
        Call3Value(WETH_ADDRESS, False, amount, WETH.fns.deposit().data),
        Call3Value(WETH_ADDRESS, False, 0, WETH.fns.withdraw(amount).data),
    ]
    tx: TxParams = {
        "chainId": chain_id,
        "to": acct.address,
        "value": amount,
        "authorizationList": [auth],
        "data": MULTICALL3.fns.aggregate3Value(calls).data,
    }

    before = await w3.eth.get_balance(acct.address)
    receipt = await send_transaction(w3, sponsor, **tx)
    after = await w3.eth.get_balance(acct.address)
    assert before + amount == after

    assert await w3.eth.get_transaction_count(acct.address) == nonce + 1

    logs = receipt["logs"]
    assert logs[0]["topics"] == [
        WETH.events.Deposit.topic,
        address_to_bytes32(acct.address),
    ]
    assert logs[1]["topics"] == [
        WETH.events.Withdrawal.topic,
        address_to_bytes32(acct.address),
    ]

    assert await w3.eth.get_code(acct.address)
    block = await w3.eth.get_block(receipt["blockNumber"], True)
    assert block["transactions"][0] == await w3.eth.get_transaction(
        receipt["transactionHash"]
    )
    receipts = await w3.eth.get_block_receipts(receipt["blockNumber"])
    assert receipts[0] == receipt


# TODO: rm flaky and enlarge num after evm mempool is ready
@pytest.mark.flaky(max_runs=5)
async def test_deploy_multi(mantra):
    w3 = mantra.async_w3
    name = "community"
    key = KEYS[name]
    owner = ADDRS[name]
    contract = CONTRACTS["ERC20MinterBurnerDecimals"]
    num = 2
    args_list = [
        (w3, contract, (f"MyToken{i}", f"MTK{i}", 18), key) for i in range(num)
    ]
    tx_results = await asyncio.gather(
        *(build_deploy_contract_async(*args) for args in args_list)
    )
    nonce = await w3.eth.get_transaction_count(owner)
    txs = [{**tx, "nonce": nonce + i} for i, (tx, _) in enumerate(tx_results)]
    receipts = await asyncio.gather(
        *(send_transaction(w3, tx["from"], **tx) for tx in txs), return_exceptions=True
    )
    for r in receipts:
        if isinstance(r, Exception):
            pytest.fail(f"send_transaction failed: {r}")
    assert len(receipts) == num
    total = 100
    token = receipts[0]["contractAddress"]
    receipt = await ERC20.fns.mint(owner, total).transact(w3, owner, to=token)
    assert receipt.status == 1
    assert await ERC20.fns.balanceOf(owner).call(w3, to=token) == total
    amt = 2
    dec_amt = 1
    inc = ContractFunction.from_abi("increaseAllowance(address,uint256)(bool)")
    dec = ContractFunction.from_abi("decreaseAllowance(address,uint256)(bool)")
    signer2 = ADDRS["signer2"]
    await inc(signer2, amt).transact(w3, owner, to=token)
    allowance = await ERC20.fns.allowance(owner, signer2).call(w3, to=token)
    assert allowance == amt
    await dec(signer2, dec_amt).transact(w3, owner, to=token)
    allowance = await ERC20.fns.allowance(owner, signer2).call(w3, to=token)
    assert allowance == amt - dec_amt

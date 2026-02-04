from pathlib import Path

import pytest
import web3
from eth_abi import encode
from eth_contract.contract import Contract as ContractAsync
from eth_contract.create2 import create2_address
from eth_contract.deploy_utils import (
    ensure_create2_deployed,
    ensure_deployed_by_create2,
    ensure_multicall3_deployed,
)
from eth_contract.erc20 import ERC20
from eth_contract.multicall3 import multicall
from eth_utils import to_checksum_address

from .utils import ACCOUNTS, ADDRS, assert_erc20_event, retry_on_nonce_mismatch

pytestmark = [pytest.mark.evmd, pytest.mark.asyncio]

GAS_PRICE = 1000000000000
WOM = to_checksum_address("0x4200000000000000000000000000000000000006")
ERC20Bin = bytes.fromhex(
    Path(__file__).parent.joinpath("configs/ERC20.bin").read_text()
)
ERC20Salt = bytes.fromhex(
    "636dd1d57837e7dce61901468217da9975548dcb3ecc24d84567feb93cd11e36"
)

BANK_PRECOMPILE = to_checksum_address("0x0000000000000000000000000000000000000804")

BANK = ContractAsync.from_abi(
    [
        "function name(string denom) view returns (string)",
        "function symbol(string denom) view returns (string)",
        "function decimals(string denom) view returns (uint8)",
        "function totalSupply(string denom) view returns (uint256)",
        "function balanceOf(address account, string denom) view returns (uint256)",
        """
        function transferFrom(
            address from,
            address to,
            uint256 value,
            string denom
        ) returns (bool)
        """,
    ]
)

TEST_DENOM = "atoken"
EXPECTED_NAME = "Test Coin"
EXPECTED_SYMBOL = "ATOKEN"
EXPECTED_DECIMALS = 18
INITIAL_SUPPLY = 1_000_000_000_000


async def deploy_erc20_wrapper(w3):
    await ensure_create2_deployed(w3, ACCOUNTS["validator"], gasPrice=GAS_PRICE)
    initcode = ERC20Bin + encode(["string", "address"], [TEST_DENOM, BANK_PRECOMPILE])
    token = await ensure_deployed_by_create2(
        w3, ACCOUNTS["validator"], initcode, ERC20Salt, gasPrice=GAS_PRICE
    )
    return token, initcode


async def test_metadata_for_denom(mantra):
    w3 = mantra.async_w3
    await ensure_multicall3_deployed(w3, ACCOUNTS["validator"], gasPrice=GAS_PRICE)

    # registered denom
    calls = [
        (BANK_PRECOMPILE, BANK.fns.name(TEST_DENOM)),
        (BANK_PRECOMPILE, BANK.fns.symbol(TEST_DENOM)),
        (BANK_PRECOMPILE, BANK.fns.decimals(TEST_DENOM)),
        (BANK_PRECOMPILE, BANK.fns.totalSupply(TEST_DENOM)),
    ]
    name, symbol, decimals, supply = await multicall(w3, calls)

    assert name == EXPECTED_NAME
    assert symbol == EXPECTED_SYMBOL
    assert decimals == EXPECTED_DECIMALS
    assert supply == INITIAL_SUPPLY

    # unregistered denom
    with pytest.raises(web3.exceptions.ContractLogicError):
        await BANK.fns.name("unknowndenom").call(w3, to=BANK_PRECOMPILE)


@pytest.mark.parametrize(
    "user_key,expected_balance",
    [
        ("community", INITIAL_SUPPLY),
        ("validator", 0),
    ],
)
async def test_balance_of(mantra, user_key, expected_balance):
    w3 = mantra.async_w3
    user = ADDRS[user_key]
    balance = await BANK.fns.balanceOf(user, TEST_DENOM).call(w3, to=BANK_PRECOMPILE)
    assert balance == expected_balance


# Only owner or authorized wrapper can call transferFrom.
async def test_bank_transfer_authorization(mantra):
    w3 = mantra.async_w3
    user = ADDRS["community"]
    recipient = ADDRS["validator"]
    amount = 1_000

    # self transfer should succeed
    balance_before = await BANK.fns.balanceOf(recipient, TEST_DENOM).call(
        w3, to=BANK_PRECOMPILE
    )
    receipt = await BANK.fns.transferFrom(user, recipient, amount, TEST_DENOM).transact(
        w3, ACCOUNTS["community"], to=BANK_PRECOMPILE, gasPrice=GAS_PRICE
    )
    assert receipt.status == 1, "self transfer should succeed"

    balance_after = await BANK.fns.balanceOf(recipient, TEST_DENOM).call(
        w3, to=BANK_PRECOMPILE
    )
    assert balance_after == balance_before + amount

    # unauthorized transfer should fail
    with pytest.raises(web3.exceptions.ContractLogicError):
        await BANK.fns.transferFrom(user, recipient, amount, TEST_DENOM).transact(
            w3, ACCOUNTS["validator"], to=BANK_PRECOMPILE, gasPrice=GAS_PRICE
        )


# Wrapper is the deterministic authorized contract for its denom.
async def test_erc20_wrapper_deploy_and_metadata(mantra):
    w3 = mantra.async_w3
    token, initcode = await deploy_erc20_wrapper(w3)

    # verify deployment
    code = await w3.eth.get_code(token)
    assert code, "ERC20 wrapper should be deployed"
    expected_addr = create2_address(initcode, ERC20Salt)
    assert token == expected_addr

    # verify metadata via wrapper
    await ensure_multicall3_deployed(w3, ACCOUNTS["validator"], gasPrice=GAS_PRICE)
    calls = [
        (token, ERC20.fns.name()),
        (token, ERC20.fns.symbol()),
        (token, ERC20.fns.decimals()),
        (token, ERC20.fns.totalSupply()),
    ]
    name, symbol, decimals, supply = await multicall(w3, calls)
    assert name == EXPECTED_NAME
    assert symbol == EXPECTED_SYMBOL
    assert decimals == EXPECTED_DECIMALS
    assert supply == INITIAL_SUPPLY


async def test_erc20_transfer(mantra):
    w3 = mantra.async_w3
    token, _ = await deploy_erc20_wrapper(w3)
    sender = ADDRS["community"]
    recipient = ADDRS["validator"]
    amount = 5_000

    sender_before = await ERC20.fns.balanceOf(sender).call(w3, to=token)
    recipient_before = await ERC20.fns.balanceOf(recipient).call(w3, to=token)

    receipt = await ERC20.fns.transfer(recipient, amount).transact(
        w3, ACCOUNTS["community"], to=token, gasPrice=GAS_PRICE
    )
    assert receipt.status == 1

    sender_after = await ERC20.fns.balanceOf(sender).call(w3, to=token)
    recipient_after = await ERC20.fns.balanceOf(recipient).call(w3, to=token)
    assert sender_after == sender_before - amount
    assert recipient_after == recipient_before + amount


# Wrapper tracks allowance and delegates to bank precompile.
async def test_erc20_approve_and_transfer_from(mantra):
    w3 = mantra.async_w3
    token, _ = await deploy_erc20_wrapper(w3)
    owner = ADDRS["community"]
    spender = ACCOUNTS["signer1"]
    spender_addr = ADDRS["signer1"]
    recipient = ADDRS["validator"]
    approve_amount = 10_000
    transfer_amount = 5_000

    # transfer without allowance should fail
    with pytest.raises(web3.exceptions.ContractLogicError):
        await ERC20.fns.transferFrom(owner, recipient, transfer_amount).transact(
            w3, spender, to=token, gasPrice=GAS_PRICE
        )

    receipt = await ERC20.fns.approve(spender_addr, approve_amount).transact(
        w3, ACCOUNTS["community"], to=token, gasPrice=GAS_PRICE
    )
    assert receipt.status == 1

    allowance = await ERC20.fns.allowance(owner, spender_addr).call(w3, to=token)
    assert allowance == approve_amount

    owner_before = await ERC20.fns.balanceOf(owner).call(w3, to=token)
    recipient_before = await ERC20.fns.balanceOf(recipient).call(w3, to=token)

    # transfer with allowance should succeed
    receipt = await retry_on_nonce_mismatch(
        ERC20.fns.transferFrom(owner, recipient, transfer_amount).transact,
        w3,
        spender,
        to=token,
        gasPrice=GAS_PRICE,
    )
    assert receipt.status == 1

    owner_after = await ERC20.fns.balanceOf(owner).call(w3, to=token)
    recipient_after = await ERC20.fns.balanceOf(recipient).call(w3, to=token)

    assert owner_after == owner_before - transfer_amount
    assert recipient_after == recipient_before + transfer_amount

    allowance_after = await ERC20.fns.allowance(owner, spender_addr).call(w3, to=token)
    assert allowance_after == approve_amount - transfer_amount


async def test_erc20_events(mantra):
    w3 = mantra.async_w3
    token, _ = await deploy_erc20_wrapper(w3)

    sender = ADDRS["community"]
    recipient = ADDRS["validator"]
    spender = ADDRS["signer1"]
    transfer_amount = 1_000
    approve_amount = 5_000

    receipt = await ERC20.fns.transfer(recipient, transfer_amount).transact(
        w3, ACCOUNTS["community"], to=token, gasPrice=GAS_PRICE
    )
    assert_erc20_event(
        receipt, ERC20.events.Transfer, sender, recipient, transfer_amount
    )

    receipt = await ERC20.fns.approve(spender, approve_amount).transact(
        w3, ACCOUNTS["community"], to=token, gasPrice=GAS_PRICE
    )
    assert_erc20_event(receipt, ERC20.events.Approval, sender, spender, approve_amount)

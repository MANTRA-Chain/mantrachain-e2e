import enum
from pathlib import Path
from typing import Unpack

import pytest
import web3
from eth_abi import encode
from eth_contract.create2 import create2_deploy
from eth_contract.deploy_utils import (
    ensure_create2_deployed,
    ensure_multicall3_deployed,
)
from eth_contract.erc20 import ERC20
from eth_contract.multicall3 import MULTICALL3, Call3, multicall
from eth_contract.utils import send_transaction
from eth_utils import to_bytes, to_checksum_address

from .utils import ACCOUNTS, ADDRS

GAS_PRICE = 1000000000000
WOM = to_checksum_address("0x4200000000000000000000000000000000000006")
ERC20Bin = bytes.fromhex(
    Path(__file__).parent.joinpath("configs/ERC20.bin").read_text()
)
ERC20Salt = bytes.fromhex(
    "636dd1d57837e7dce61901468217da9975548dcb3ecc24d84567feb93cd11e36"
)


class BankMethod(enum.IntEnum):
    NAME = 0
    SYMBOL = 1
    DECIMALS = 2
    TOTAL_SUPPLY = 3
    BALANCE_OF = 4
    TRANSFER_FROM = 5

    def args(self, *args: Unpack[bytes]) -> bytes:
        return b"".join([bytes([self.value]), *args])


@pytest.mark.asyncio
async def test_bank_precompile(mantra):
    w3 = mantra.async_w3
    await ensure_multicall3_deployed(w3, ACCOUNTS["validator"], gasPrice=GAS_PRICE)

    bank = to_checksum_address("0x0000000000000000000000000000000000000807")
    user = ADDRS["community"]
    denom = "atoken"
    calls = [
        Call3(bank, data=BankMethod.NAME.args(denom.encode())),
        Call3(bank, data=BankMethod.SYMBOL.args(denom.encode())),
        Call3(bank, data=BankMethod.DECIMALS.args(denom.encode())),
        Call3(bank, data=BankMethod.TOTAL_SUPPLY.args(denom.encode())),
        Call3(
            bank, data=BankMethod.BALANCE_OF.args(to_bytes(hexstr=user), denom.encode())
        ),
    ]
    results = await MULTICALL3.fns.aggregate3(calls).call(w3)
    expected = (
        (True, b"Test Coin"),
        (True, b"ATOKEN"),
        (True, bytes([18])),
        (True, (1000000000000).to_bytes(32, "big")),
        (True, (1000000000000).to_bytes(32, "big")),
    )
    assert expected == results

    # owner can transfer funds on bank precompile directly
    recipient = ADDRS["validator"]
    amount = 1000
    data = BankMethod.TRANSFER_FROM.args(
        to_bytes(hexstr=user),
        to_bytes(hexstr=recipient),
        amount.to_bytes(32, "big"),
        denom.encode(),
    )
    await send_transaction(
        w3, ACCOUNTS["community"], to=bank, data=data, gasPrice=GAS_PRICE
    )

    with pytest.raises(web3.exceptions.ContractLogicError):
        # wrong user fail
        await send_transaction(
            w3, ACCOUNTS["validator"], to=bank, data=data, gasPrice=GAS_PRICE
        )


@pytest.mark.asyncio
async def test_bank_erc20(mantra):
    w3 = mantra.async_w3
    await ensure_create2_deployed(w3, ACCOUNTS["validator"], gasPrice=GAS_PRICE)
    await ensure_multicall3_deployed(w3, ACCOUNTS["validator"], gasPrice=GAS_PRICE)

    bank = to_checksum_address("0x0000000000000000000000000000000000000807")
    user = ADDRS["community"]
    denom = "atoken"

    initcode = ERC20Bin + encode(["string", "address"], [denom, bank])
    token = await create2_deploy(
        w3, ACCOUNTS["validator"], initcode, ERC20Salt, gasPrice=GAS_PRICE
    )

    test_user = to_checksum_address(b"\x01" * 20)
    await ERC20.fns.transfer(test_user, 1).transact(
        w3, ACCOUNTS["community"], to=token, gasPrice=GAS_PRICE
    )

    expected = ["Test Coin", "ATOKEN", 18, 1000000000000, 1]
    calls = [
        (token, ERC20.fns.name()),
        (token, ERC20.fns.symbol()),
        (token, ERC20.fns.decimals()),
        (token, ERC20.fns.totalSupply()),
        (token, ERC20.fns.balanceOf(test_user)),
    ]
    result = await multicall(w3, calls)
    assert expected == result

    # owner can transfer funds on bank precompile directly
    recipient = ADDRS["validator"]
    amount = 1000
    before = (
        await ERC20.fns.balanceOf(user).call(w3, to=token),
        await ERC20.fns.balanceOf(recipient).call(w3, to=token),
    )
    await ERC20.fns.transfer(recipient, amount).transact(
        w3, ACCOUNTS["community"], to=token, gasPrice=GAS_PRICE
    )
    after = (
        await ERC20.fns.balanceOf(user).call(w3, to=token),
        await ERC20.fns.balanceOf(recipient).call(w3, to=token),
    )
    assert after == (before[0] - amount, before[1] + amount)

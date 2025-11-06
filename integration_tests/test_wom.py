import pytest
from eth_contract.erc20 import ERC20
from eth_contract.utils import send_transaction
from eth_utils import to_checksum_address

from .utils import ACCOUNTS, deploy_wom


@pytest.mark.asyncio
async def test_wom(mantra):
    deployer = ACCOUNTS["community"]
    w3 = mantra.async_w3
    wom = await deploy_wom(w3, deployer)
    code = await w3.eth.get_code(wom)
    assert len(code) > 2, "Contract not deployed"
    deposit_amt = 1000
    await send_transaction(w3, deployer, to=wom, value=deposit_amt)
    spender = to_checksum_address(b"\x01" * 20)
    approval_amt = 500
    await ERC20.fns.approve(spender, approval_amt).transact(w3, deployer, to=wom)
    name = await ERC20.fns.name().call(w3, to=wom)
    assert name == "Wrapped OM"
    symbol = await ERC20.fns.symbol().call(w3, to=wom)
    assert symbol == "wOM"
    decimals = await ERC20.fns.decimals().call(w3, to=wom)
    assert decimals == 18
    balance = await ERC20.fns.balanceOf(deployer.address).call(w3, to=wom)
    assert balance == deposit_amt
    allowance = await ERC20.fns.allowance(deployer.address, spender).call(w3, to=wom)
    assert allowance == approval_amt

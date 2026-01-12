import pytest
from eth_contract.contract import Contract

from .utils import (
    ADDRS,
    DEFAULT_DENOM,
    build_contract,
    eth_to_bech32,
)

PRECOMPILE = Contract(build_contract("IBank")["abi"])
BANK = "0x0000000000000000000000000000000000000804"

pytestmark = pytest.mark.asyncio


async def assert_balances_structure(balances):
    assert isinstance(balances, (list, tuple))
    for addr, amount in balances:
        assert addr.startswith("0x") and isinstance(addr, str)
        assert isinstance(amount, int) and amount >= 0


async def test_bank(mantra):
    cli = mantra.cosmos_cli()
    w3 = mantra.async_w3
    community = ADDRS["community"]

    balances = await PRECOMPILE.fns.balances(community).call(w3, to=BANK)
    await assert_balances_structure(balances)
    assert balances
    erc20_addr, bal_amount = balances[0]
    assert bal_amount == cli.balance(eth_to_bech32(community))
    height = await w3.eth.block_number
    total_supply = await PRECOMPILE.fns.totalSupply().call(
        w3, to=BANK, block_identifier=height
    )
    await assert_balances_structure(total_supply)
    assert total_supply
    erc20_addr, supply_amount = total_supply[0]
    assert supply_amount == int(
        cli.total_supply_of(DEFAULT_DENOM, height=height)["amount"]
    )
    supply = await PRECOMPILE.fns.supplyOf(erc20_addr).call(
        w3, to=BANK, block_identifier=height
    )
    assert supply == supply_amount

    fake_token = "0x1234567890123456789012345678901234567890"
    assert await PRECOMPILE.fns.supplyOf(fake_token).call(w3, to=BANK) == 0

import pytest
from web3 import AsyncWeb3
from web3.types import Wei

from .utils import ADDRS

pytestmark = pytest.mark.asyncio


async def test_gas_price(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    gas_price = await w3.eth.gas_price
    assert gas_price > 0
    tx = {
        "from": ADDRS["validator"],
        "to": ADDRS["community"],
        "value": Wei(1000000000000000000),
    }
    estimated_gas = await w3.eth.estimate_gas(tx)
    assert estimated_gas > 0


async def test_gas_limit(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    latest_block = await w3.eth.get_block("latest")
    gas_limit = latest_block["gasLimit"]
    assert gas_limit > 0

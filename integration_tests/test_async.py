import pytest
from web3 import AsyncWeb3
from web3.types import Wei

from .utils import ADDRS

pytestmark = pytest.mark.asyncio


@pytest.mark.connect
async def test_connect_exception(connect_mantra):
    await test_gas_price(None, connect_mantra)


async def test_gas_price(mantra, connect_mantra):
    w3: AsyncWeb3 = connect_mantra.async_w3
    gas_price = await w3.eth.gas_price
    assert gas_price > 0
    tx = {
        "from": ADDRS["community"],
        "to": ADDRS["signer1"],
        "value": Wei(1000000000000000000),
    }
    estimated_gas = await w3.eth.estimate_gas(tx)
    assert estimated_gas > 0


@pytest.mark.connect
async def test_connect_gas_limit(connect_mantra):
    await test_gas_limit(None, connect_mantra)


async def test_gas_limit(mantra, connect_mantra):
    w3: AsyncWeb3 = connect_mantra.async_w3
    latest_block = await w3.eth.get_block("latest")
    gas_limit = latest_block["gasLimit"]
    assert gas_limit > 0

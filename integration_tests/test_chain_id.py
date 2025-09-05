from pathlib import Path

import pytest
from eth_contract.utils import send_transaction

from .network import setup_custom_mantra
from .utils import ACCOUNTS, ADDRS

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def custom_mantra(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp("chain-id")
    yield from setup_custom_mantra(
        path,
        26600,
        Path(__file__).parent / "configs/chain-id.jsonnet",
        chain=chain,
    )


async def test_chain_id(custom_mantra):
    w3 = custom_mantra.async_w3
    assert await w3.eth.chain_id == 9001
    tx = {"to": ADDRS["signer1"], "value": 1000}
    await send_transaction(w3, ACCOUNTS["community"], **tx)

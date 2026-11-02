import pytest

from .network import setup_mantra
from .utils import ACCOUNTS, ADDRS
from .utils import send_transaction_async as send_transaction

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def custom_mantra(request, tmp_path_factory):
    yield from setup_mantra(request, tmp_path_factory, "chain-id", 26600)


async def test_chain_id(custom_mantra):
    w3 = custom_mantra.async_w3
    assert await w3.eth.chain_id == 9001
    tx = {"to": ADDRS["signer1"], "value": 1000}
    await send_transaction(w3, ACCOUNTS["community"], **tx)

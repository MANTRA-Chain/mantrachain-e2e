import pytest

from .ibc_utils import assert_ibc_evmd_flow, prepare_network

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def ibc(request, tmp_path_factory):
    "prepare-network"
    name = "ibc_evmd"
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp(name)
    yield from prepare_network(
        path, name, chain, b_chain="evm-canary-net-1", cmd="evmd"
    )


def test_ibc_transfer(ibc):
    assert_ibc_evmd_flow(ibc)

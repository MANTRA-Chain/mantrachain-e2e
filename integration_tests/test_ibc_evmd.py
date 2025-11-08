import pytest

from .ibc_utils import assert_hermes_transfer, prepare_network

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
    cli = ibc.ibc1.cosmos_cli()
    cli2 = ibc.ibc2.cosmos_cli()
    prefix = "cosmos"
    amt = 10
    amt2 = 5
    # evm-canary-net-1 signer2 -> mcantra-canary-net-1 signer1 10atest
    dst_denom, _ = assert_hermes_transfer(
        ibc.hermes,
        cli2,
        "signer2",
        amt,
        cli,
        cli.address("signer1"),
        denom="atest",
        prefix=prefix,
    )
    # mantra-canary-net-1 signer1 -> evm-canary-net-1 signer2 with 5ibc_token
    assert_hermes_transfer(
        ibc.hermes,
        cli,
        "signer1",
        amt2,
        cli2,
        cli2.address("signer2"),
        denom=dst_denom,
    )
    # mantra-canary-net-1 signer1 -> evm-canary-net-1 signer2 with 10baseunit
    dst_denom2, _ = assert_hermes_transfer(
        ibc.hermes,
        cli,
        "signer1",
        amt,
        cli2,
        cli2.address("signer2"),
    )
    # evm-canary-net-1 signer2 -> mcantra-canary-net-1 signer1 5ibc_token
    assert_hermes_transfer(
        ibc.hermes,
        cli2,
        "signer2",
        amt2,
        cli,
        cli.address("signer1"),
        denom=dst_denom2,
        prefix=prefix,
    )

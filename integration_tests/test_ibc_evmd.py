import pytest

from .ibc_utils import (
    assert_hermes_transfer,
    assert_ibc_transfer,
    ibc_denom_hash,
    prepare_network,
)
from .utils import (
    ADDRS,
    DEFAULT_DENOM,
    eth_to_bech32,
)

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
    signer1 = ADDRS["signer1"]
    community = ADDRS["community"]
    addr_signer1 = eth_to_bech32(signer1)
    denom = "atest"
    prefix = "cosmos"
    port = "transfer"
    channel = "channel-0"

    # evm-canary-net-1 signer2 -> mantra-canary-net-1 signer1 100atest
    transfer_amt = 100
    dst_denom, _ = assert_hermes_transfer(
        ibc.hermes,
        cli2,
        "signer2",
        transfer_amt,
        cli,
        addr_signer1,
        denom=denom,
        prefix=prefix,
    )

    # mantra-canary-net-1 signer1 -> evm-canary-net-1 community eth addr with 5uom
    path = f"{port}/{channel}/{DEFAULT_DENOM}"
    denom_hash = ibc_denom_hash(path)
    dst_denom = f"ibc/{denom_hash}"
    amt = 5
    assert_ibc_transfer(
        cli,
        cli2,
        addr_signer1,
        community,
        amt,
        dst_denom,
    )

import hashlib

import pytest

from .ibc_utils import hermes_transfer, prepare_network
from .utils import (
    ADDRS,
    DEFAULT_DENOM,
    eth_to_bech32,
    wait_for_fn,
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


def wait_for_balance_change(cli, addr, denom, init_balance):
    def check_balance():
        current_balance = cli.balance(addr, denom)
        return current_balance if current_balance != init_balance else None

    return wait_for_fn("balance change", check_balance)


@pytest.mark.flaky(max_runs=2)
def test_ibc_transfer(ibc):
    cli = ibc.ibc1.cosmos_cli()
    cli2 = ibc.ibc2.cosmos_cli()
    signer1 = ADDRS["signer1"]
    community = ADDRS["community"]
    prefix = "cosmos"
    addr_signer1 = eth_to_bech32(signer1)
    addr_community = eth_to_bech32(community, prefix=prefix)
    denom = "atest"

    # evm-canary-net-1 signer2 -> mantra-canary-net-1 signer1 100atest
    transfer_amt = 100
    src_chain = "evm-canary-net-1"
    dst_chain = "mantra-canary-net-1"
    path, escrow_addr = hermes_transfer(
        ibc,
        src_chain,
        "signer2",
        transfer_amt,
        dst_chain,
        addr_signer1,
        denom=denom,
        prefix=prefix,
    )
    denom_hash = hashlib.sha256(path.encode()).hexdigest().upper()
    dst_denom = f"ibc/{denom_hash}"
    signer1_balance_bf = cli.balance(addr_signer1, dst_denom)
    signer1_balance = wait_for_balance_change(
        cli, addr_signer1, dst_denom, signer1_balance_bf
    )
    assert signer1_balance == signer1_balance_bf + transfer_amt
    assert cli.ibc_denom_hash(path) == denom_hash
    cli2.balance(escrow_addr, denom=denom) == transfer_amt

    # mantra-canary-net-1 signer1 -> evm-canary-net-1 community eth addr with 5uom
    parts = path.rsplit("/", 1)
    path = f"{parts[0]}/uom"
    denom_hash = hashlib.sha256(path.encode()).hexdigest().upper()
    dst_denom = f"ibc/{denom_hash}"
    amount = 5
    rsp = cli.ibc_transfer(
        community,
        f"{amount}{DEFAULT_DENOM}",
        "channel-0",
        from_=addr_signer1,
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    community_balance_bf = cli2.balance(addr_community, dst_denom)
    community_balance = wait_for_balance_change(
        cli2, addr_community, dst_denom, community_balance_bf
    )
    assert community_balance == community_balance_bf + amount

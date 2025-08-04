import hashlib
import math

import pytest

from .ibc_utils import hermes_transfer, prepare_network
from .utils import (
    ADDRS,
    CONTRACTS,
    DEFAULT_DENOM,
    assert_balance,
    escrow_address,
    eth_to_bech32,
    find_duplicate,
    get_contract,
    ibc_denom_address,
    parse_events_rpc,
    wait_for_fn,
)


@pytest.fixture(scope="module")
def ibc(tmp_path_factory):
    "prepare-network"
    name = "ibc"
    path = tmp_path_factory.mktemp(name)
    yield from prepare_network(path, name)


def assert_dynamic_fee(cli):
    # assert that the relayer transactions do enables the dynamic fee extension option.
    criteria = "message.action='/ibc.core.channel.v1.MsgChannelOpenInit'"
    tx = cli.tx_search(criteria)["txs"][0]
    events = parse_events_rpc(tx["events"])
    fee = int(events["tx"]["fee"].removesuffix(DEFAULT_DENOM))
    gas = int(tx["gas_wanted"])
    # the effective fee is decided by the max_priority_fee (base fee is zero)
    # rather than the normal gas price
    cosmos_evm_dynamic_fee = 10000000000000000 / 1e18
    assert fee == math.ceil(gas * cosmos_evm_dynamic_fee)


def assert_dup_events(cli):
    # check duplicate OnRecvPacket events
    criteria = "message.action='/ibc.core.channel.v1.MsgRecvPacket'"
    events = cli.tx_search(criteria)["txs"][0]["events"]
    for event in events:
        dup = find_duplicate(event["attributes"])
        assert not dup, f"duplicate {dup} in {event['type']}"


def test_ibc_transfer(ibc):
    src_amount = 10
    port = "transfer"
    channel = "channel-0"
    community = "community"
    dst_addr = eth_to_bech32(ADDRS[community])
    hermes_transfer(ibc, port, channel, src_amount, dst_addr)
    RATIO = 1  # the decimal places difference
    dst_amount = src_amount * RATIO
    path = f"{port}/{channel}/{DEFAULT_DENOM}"
    denom_hash = hashlib.sha256(path.encode()).hexdigest().upper()
    dst_denom = f"ibc/{denom_hash}"
    cli = ibc.ibc1.cosmos_cli()
    old_dst_balance = cli.balance(dst_addr, dst_denom)
    new_dst_balance = 0

    def check_balance_change():
        nonlocal new_dst_balance
        new_dst_balance = cli.balance(dst_addr, dst_denom)
        return new_dst_balance != old_dst_balance

    wait_for_fn("balance change", check_balance_change)
    assert old_dst_balance + dst_amount == new_dst_balance
    assert cli.ibc_denom_hash(path) == denom_hash
    cli2 = ibc.ibc2.cosmos_cli()
    assert_balance(cli2, ibc.ibc2.w3, escrow_address(port, channel)) == dst_amount
    assert_dynamic_fee(cli)
    assert_dup_events(cli)

    ibc_denom_addr = ibc_denom_address(dst_denom)
    erc20_contract = get_contract(ibc.ibc1.w3, ibc_denom_addr, CONTRACTS["IERC20"])
    assert erc20_contract.caller.balanceOf(ADDRS["community"]) == src_amount

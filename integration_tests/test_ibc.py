import hashlib
import math

import pytest

from .ibc_utils import hermes_transfer, prepare_network
from .utils import (
    ADDRS,
    CONTRACTS,
    DEFAULT_DENOM,
    KEYS,
    assert_balance,
    derive_new_account,
    escrow_address,
    eth_to_bech32,
    find_duplicate,
    get_contract,
    ibc_denom_address,
    parse_events_rpc,
    send_transaction,
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
    cosmos_evm_dynamic_fee = 10000000000000000 / 10**18
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
    w3 = ibc.ibc1.w3
    erc20_contract = get_contract(w3, ibc_denom_addr, CONTRACTS["IERC20"])
    total = erc20_contract.caller.totalSupply()
    balance = erc20_contract.caller.balanceOf(ADDRS[community])
    assert total == balance == src_amount
    receiver = derive_new_account(2).address
    amt = 5
    tx = erc20_contract.functions.transfer(receiver, amt).build_transaction(
        {
            "from": ADDRS[community],
            "gasPrice": w3.eth.gas_price,
            "nonce": w3.eth.get_transaction_count(ADDRS[community]),
        }
    )
    gas = w3.eth.estimate_gas(tx)
    tx["gas"] = gas
    res = send_transaction(
        w3,
        tx,
        key=KEYS[community],
    )
    assert res.status == 1
    assert erc20_contract.caller.balanceOf(ADDRS[community]) == balance - amt
    assert erc20_contract.caller.balanceOf(receiver) == amt

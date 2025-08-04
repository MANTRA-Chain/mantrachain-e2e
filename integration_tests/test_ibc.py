import hashlib
import math

import pytest
from eth_contract.erc20 import ERC20
from eth_contract.utils import send_transaction
from web3.types import TxParams

from .ibc_utils import hermes_transfer, prepare_network
from .utils import (
    ADDRS,
    DEFAULT_DENOM,
    assert_balance,
    assert_create_tokenfactory_denom,
    denom_to_erc20_address,
    derive_new_account,
    escrow_address,
    eth_to_bech32,
    find_duplicate,
    ibc_denom_address,
    parse_events_rpc,
    wait_for_fn,
)

pytestmark = pytest.mark.asyncio


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


async def test_ibc_transfer(ibc):
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

    ibc_erc20_addr = ibc_denom_address(dst_denom)
    w3 = ibc.ibc1.async_w3

    # TODO: fix after display align with unit https://github.com/cosmos/evm/issues/396
    assert (await ERC20.fns.decimals().call(w3, to=ibc_erc20_addr)) == 0

    total = await ERC20.fns.totalSupply().call(w3, to=ibc_erc20_addr)
    sender = ADDRS[community]
    receiver = derive_new_account(2).address
    balance = await ERC20.fns.balanceOf(sender).call(w3, to=ibc_erc20_addr)
    assert total == balance == src_amount
    amt = 5

    tx = TxParams(
        {
            "from": sender,
            "to": ibc_erc20_addr,
            "data": ERC20.fns.transfer(receiver, amt).data,
            "gasPrice": await w3.eth.gas_price,
        }
    )
    tx["gas"] = await w3.eth.estimate_gas(tx)
    await send_transaction(w3, sender, **tx)
    assert balance - amt == await ERC20.fns.balanceOf(sender).call(
        w3, to=ibc_erc20_addr
    )
    assert amt == await ERC20.fns.balanceOf(receiver).call(w3, to=ibc_erc20_addr)

    receiver2 = ADDRS["signer2"]
    receiver3 = ADDRS["signer1"]
    amt2 = 2

    tx = TxParams(
        {
            "from": sender,
            "to": ibc_erc20_addr,
            "data": ERC20.fns.approve(receiver2, amt2).data,
            "gasPrice": await w3.eth.gas_price,
        }
    )
    tx["gas"] = await w3.eth.estimate_gas(tx)
    await send_transaction(w3, sender, **tx)
    assert (
        await ERC20.fns.allowance(sender, receiver2).call(w3, to=ibc_erc20_addr)
    ) == amt2

    tx = TxParams(
        {
            "from": receiver2,
            "to": ibc_erc20_addr,
            "data": ERC20.fns.transferFrom(sender, receiver3, amt2).data,
            "gasPrice": await w3.eth.gas_price,
        }
    )
    tx["gas"] = await w3.eth.estimate_gas(tx)
    await send_transaction(w3, receiver2, **tx)
    assert (
        await ERC20.fns.balanceOf(sender).call(w3, to=ibc_erc20_addr)
    ) == balance - amt - amt2
    assert (await ERC20.fns.balanceOf(receiver2).call(w3, to=ibc_erc20_addr)) == 0
    assert (await ERC20.fns.balanceOf(receiver3).call(w3, to=ibc_erc20_addr)) == amt2

    subdenom = "test"
    # check create tokenfactory denom
    denom = assert_create_tokenfactory_denom(
        cli, subdenom, _from=cli.address(community), gas=620000
    )
    tf_erc20_addr = denom_to_erc20_address(denom)
    assert (await ERC20.fns.decimals().call(w3, to=tf_erc20_addr)) == 0

import hashlib
import math

import pytest
from eth_contract.erc20 import ERC20

from .ibc_utils import hermes_transfer, prepare_network
from .utils import (
    ADDRS,
    DEFAULT_DENOM,
    assert_balance,
    assert_burn_tokenfactory_denom,
    assert_create_tokenfactory_denom,
    assert_mint_tokenfactory_denom,
    assert_transfer_tokenfactory_denom,
    denom_to_erc20_address,
    derive_new_account,
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


async def test_ibc_transfer(ibc, tmp_path):
    w3 = ibc.ibc1.async_w3
    cli = ibc.ibc1.cosmos_cli()
    cli2 = ibc.ibc2.cosmos_cli()
    signer1 = ADDRS["signer1"]
    signer2 = ADDRS["signer2"]
    addr_signer1 = eth_to_bech32(signer1)

    # mantra-canary-net-2 signer2 -> mantra-canary-net-1 signer1 10uom
    ibc_transfer_amt = 10
    src_chain = "mantra-canary-net-2"
    dst_chain = "mantra-canary-net-1"
    path, escrow_addr = hermes_transfer(
        ibc, src_chain, dst_chain, ibc_transfer_amt, addr_signer1
    )
    denom_hash = hashlib.sha256(path.encode()).hexdigest().upper()
    dst_denom = f"ibc/{denom_hash}"
    signer1_balance_bf = cli.balance(addr_signer1, dst_denom)
    signer1_balance = 0

    def check_balance_change():
        nonlocal signer1_balance
        signer1_balance = cli.balance(addr_signer1, dst_denom)
        return signer1_balance != signer1_balance_bf

    wait_for_fn("balance change", check_balance_change)
    assert signer1_balance == signer1_balance_bf + ibc_transfer_amt
    assert cli.ibc_denom_hash(path) == denom_hash
    assert_balance(cli2, ibc.ibc2.w3, escrow_addr) == ibc_transfer_amt
    assert_dynamic_fee(cli)
    assert_dup_events(cli)

    ibc_erc20_addr = ibc_denom_address(dst_denom)

    assert (await ERC20.fns.decimals().call(w3, to=ibc_erc20_addr)) == 0
    total = await ERC20.fns.totalSupply().call(w3, to=ibc_erc20_addr)
    receiver = derive_new_account(4).address
    addr_receiver = eth_to_bech32(receiver)

    signer1_balance_eth_bf = await ERC20.fns.balanceOf(signer1).call(
        w3, to=ibc_erc20_addr
    )
    signer2_balance_eth_bf = await ERC20.fns.balanceOf(signer2).call(
        w3, to=ibc_erc20_addr
    )
    receiver_balance_eth_bf = await ERC20.fns.balanceOf(receiver).call(
        w3, to=ibc_erc20_addr
    )
    assert total == signer1_balance_eth_bf == ibc_transfer_amt

    # signer1 transfer 5ibc_erc20 to receiver
    ibc_erc20_transfer_amt = 5
    await ERC20.fns.transfer(receiver, ibc_erc20_transfer_amt).transact(
        w3,
        signer1,
        to=ibc_erc20_addr,
        gasPrice=(await w3.eth.gas_price),
    )
    signer1_balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=ibc_erc20_addr)
    assert signer1_balance_eth == signer1_balance_eth_bf - ibc_erc20_transfer_amt
    signer1_balance_eth_bf = signer1_balance_eth

    receiver_balance_eth = await ERC20.fns.balanceOf(receiver).call(
        w3, to=ibc_erc20_addr
    )
    assert receiver_balance_eth == receiver_balance_eth_bf + ibc_erc20_transfer_amt
    receiver_balance_eth_bf = receiver_balance_eth

    # signer1 approve 2ibc_erc20 to signer2
    ibc_erc20_approve_amt = 2
    await ERC20.fns.approve(signer2, ibc_erc20_approve_amt).transact(
        w3,
        signer1,
        to=ibc_erc20_addr,
        gasPrice=(await w3.eth.gas_price),
    )
    allowance = await ERC20.fns.allowance(signer1, signer2).call(w3, to=ibc_erc20_addr)
    assert allowance == ibc_erc20_approve_amt

    # transferFrom signer1 to receiver via signer2 with 2ibc_erc20
    await ERC20.fns.transferFrom(signer1, receiver, ibc_erc20_approve_amt).transact(
        w3,
        signer2,
        to=ibc_erc20_addr,
        gasPrice=(await w3.eth.gas_price),
    )
    signer1_balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=ibc_erc20_addr)
    assert signer1_balance_eth == signer1_balance_eth_bf - ibc_erc20_approve_amt
    signer1_balance_eth_bf = signer1_balance_eth

    signer2_balance_eth = await ERC20.fns.balanceOf(signer2).call(w3, to=ibc_erc20_addr)
    assert signer2_balance_eth == signer2_balance_eth_bf
    receiver_balance_eth = await ERC20.fns.balanceOf(receiver).call(
        w3, to=ibc_erc20_addr
    )
    assert receiver_balance_eth == receiver_balance_eth_bf + ibc_erc20_approve_amt
    receiver_balance_eth_bf = receiver_balance_eth

    # check create mint transfer and burn tokenfactory denom
    subdenom = "test"
    gas = 300000
    ibc_erc20_transfer_amt = 10**6
    transfer_amt = 1
    burn_amt = 10**3
    denom = assert_create_tokenfactory_denom(
        cli, subdenom, _from=addr_signer1, gas=620000
    )
    tf_erc20_addr = denom_to_erc20_address(denom)
    assert (await ERC20.fns.decimals().call(w3, to=tf_erc20_addr)) == 0
    total = await ERC20.fns.totalSupply().call(w3, to=tf_erc20_addr)
    signer1_balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    balance = cli.balance(addr_signer1, denom)
    assert total == balance == signer1_balance_eth == 0

    balance = assert_mint_tokenfactory_denom(
        cli, denom, ibc_erc20_transfer_amt, _from=addr_signer1, gas=gas
    )
    signer1_balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    total = await ERC20.fns.totalSupply().call(w3, to=tf_erc20_addr)
    assert total == balance == signer1_balance_eth == ibc_erc20_transfer_amt

    balance = assert_transfer_tokenfactory_denom(
        cli, denom, addr_receiver, transfer_amt, _from=addr_signer1, gas=gas
    )
    signer1_balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    assert balance == signer1_balance_eth == ibc_erc20_transfer_amt - transfer_amt

    balance = assert_burn_tokenfactory_denom(
        cli, denom, burn_amt, _from=addr_signer1, gas=gas
    )
    signer1_balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    assert (
        balance
        == signer1_balance_eth
        == ibc_erc20_transfer_amt - transfer_amt - burn_amt
    )

    balance = cli.balance(addr_receiver, denom)
    signer1_balance_eth = await ERC20.fns.balanceOf(receiver).call(w3, to=tf_erc20_addr)
    assert balance == signer1_balance_eth == transfer_amt

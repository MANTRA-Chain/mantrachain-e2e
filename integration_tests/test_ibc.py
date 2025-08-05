import hashlib
import math

import pytest
from eth_contract.deploy_utils import (
    ensure_create2_deployed,
    ensure_deployed_by_create2,
)
from eth_contract.erc20 import ERC20
from eth_contract.utils import get_initcode
from eth_contract.weth import WETH

from .ibc_utils import hermes_transfer, prepare_network
from .utils import (
    ADDRS,
    DEFAULT_DENOM,
    WETH9_ARTIFACT,
    WETH_ADDRESS,
    WETH_SALT,
    assert_balance,
    assert_burn_tokenfactory_denom,
    assert_create_tokenfactory_denom,
    assert_mint_tokenfactory_denom,
    assert_transfer_tokenfactory_denom,
    denom_to_erc20_address,
    derive_new_account,
    escrow_address,
    eth_to_bech32,
    find_duplicate,
    ibc_denom_address,
    module_address,
    parse_events_rpc,
    submit_gov_proposal,
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
    account = (await w3.eth.accounts)[0]
    await ensure_create2_deployed(w3, account)
    await ensure_deployed_by_create2(
        w3,
        account,
        get_initcode(WETH9_ARTIFACT),
        salt=WETH_SALT,
    )
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

    assert (await ERC20.fns.decimals().call(w3, to=ibc_erc20_addr)) == 0
    total = await ERC20.fns.totalSupply().call(w3, to=ibc_erc20_addr)
    sender = ADDRS[community]
    receiver = derive_new_account(2).address
    addr_sender = eth_to_bech32(sender)
    addr_receiver = eth_to_bech32(receiver)
    balance_eth = await ERC20.fns.balanceOf(sender).call(w3, to=ibc_erc20_addr)
    assert total == balance_eth == src_amount
    amt = 5

    await ERC20.fns.transfer(receiver, amt).transact(
        w3,
        sender,
        to=ibc_erc20_addr,
        gasPrice=(await w3.eth.gas_price),
    )
    assert balance_eth - amt == await ERC20.fns.balanceOf(sender).call(
        w3, to=ibc_erc20_addr
    )
    assert amt == (await ERC20.fns.balanceOf(receiver).call(w3, to=ibc_erc20_addr))

    receiver2 = ADDRS["signer2"]
    receiver3 = ADDRS["signer1"]
    amt2 = 2

    await ERC20.fns.approve(receiver2, amt2).transact(
        w3,
        sender,
        to=ibc_erc20_addr,
        gasPrice=(await w3.eth.gas_price),
    )
    allowance = await ERC20.fns.allowance(sender, receiver2).call(w3, to=ibc_erc20_addr)
    assert allowance == amt2

    await ERC20.fns.transferFrom(sender, receiver3, amt2).transact(
        w3,
        receiver2,
        to=ibc_erc20_addr,
        gasPrice=(await w3.eth.gas_price),
    )
    assert (
        await ERC20.fns.balanceOf(sender).call(w3, to=ibc_erc20_addr)
    ) == balance_eth - amt - amt2
    assert (await ERC20.fns.balanceOf(receiver2).call(w3, to=ibc_erc20_addr)) == 0
    assert (await ERC20.fns.balanceOf(receiver3).call(w3, to=ibc_erc20_addr)) == amt2

    # check native erc20 transfer
    submit_gov_proposal(
        ibc.ibc1,
        tmp_path,
        messages=[
            {
                "@type": "/cosmos.evm.erc20.v1.MsgRegisterERC20",
                "signer": eth_to_bech32(module_address("gov")),
                "erc20addresses": [WETH_ADDRESS],
            }
        ],
    )

    assert (await ERC20.fns.decimals().call(w3, to=WETH_ADDRESS)) == 18
    total = await ERC20.fns.totalSupply().call(w3, to=WETH_ADDRESS)
    balance_eth = await ERC20.fns.balanceOf(sender).call(w3, to=WETH_ADDRESS)
    assert total == balance_eth == 0

    weth = WETH(to=WETH_ADDRESS)
    deposit_amt = 1000
    res = await weth.fns.deposit().transact(w3, sender, value=deposit_amt)
    assert res.status == 1
    total = await ERC20.fns.totalSupply().call(w3, to=WETH_ADDRESS)
    balance_eth = await ERC20.fns.balanceOf(sender).call(w3, to=WETH_ADDRESS)
    assert total == balance_eth == deposit_amt

    rsp = cli.convert_erc20(WETH_ADDRESS, deposit_amt, _from=addr_sender, gas=999999)
    assert rsp["code"] == 0, rsp["raw_log"]
    assert await ERC20.fns.balanceOf(sender).call(w3, to=WETH_ADDRESS) == 0
    erc20_denom = f"erc20:{WETH_ADDRESS}"
    assert cli.balance(addr_sender, erc20_denom) == deposit_amt
    transfer_amt = 10
    rsp = cli.transfer(addr_sender, addr_receiver, f"{transfer_amt}{erc20_denom}")
    assert rsp["code"] == 0, rsp["raw_log"]
    assert cli.balance(addr_sender, erc20_denom) == deposit_amt - transfer_amt
    assert cli.balance(addr_receiver, erc20_denom) == transfer_amt

    # check create mint transfer and burn tokenfactory denom
    subdenom = "test"
    gas = 300000
    amt = 10**6
    transfer_amt = 1
    burn_amt = 10**3
    denom = assert_create_tokenfactory_denom(
        cli, subdenom, _from=addr_sender, gas=620000
    )
    tf_erc20_addr = denom_to_erc20_address(denom)
    assert (await ERC20.fns.decimals().call(w3, to=tf_erc20_addr)) == 0
    total = await ERC20.fns.totalSupply().call(w3, to=tf_erc20_addr)
    balance_eth = await ERC20.fns.balanceOf(sender).call(w3, to=tf_erc20_addr)
    balance = cli.balance(addr_sender, denom)
    assert total == balance == balance_eth == 0

    balance = assert_mint_tokenfactory_denom(
        cli, denom, amt, _from=addr_sender, gas=gas
    )
    balance_eth = await ERC20.fns.balanceOf(sender).call(w3, to=tf_erc20_addr)
    total = await ERC20.fns.totalSupply().call(w3, to=tf_erc20_addr)
    assert total == balance == balance_eth == amt

    balance = assert_transfer_tokenfactory_denom(
        cli, denom, addr_receiver, transfer_amt, _from=addr_sender, gas=gas
    )
    balance_eth = await ERC20.fns.balanceOf(sender).call(w3, to=tf_erc20_addr)
    assert balance == balance_eth == amt - transfer_amt

    balance = assert_burn_tokenfactory_denom(
        cli, denom, burn_amt, _from=addr_sender, gas=gas
    )
    balance_eth = await ERC20.fns.balanceOf(sender).call(w3, to=tf_erc20_addr)
    assert balance == balance_eth == amt - transfer_amt - burn_amt

    balance = cli.balance(addr_receiver, denom)
    balance_eth = await ERC20.fns.balanceOf(receiver).call(w3, to=tf_erc20_addr)
    assert balance == balance_eth == transfer_amt

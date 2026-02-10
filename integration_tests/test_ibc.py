import json
import time

import pytest
from eth_contract.contract import Contract
from eth_contract.erc20 import ERC20
from pystarport.utils import wait_for_fn_async
from web3 import AsyncWeb3

from .ibc_utils import (
    assert_hermes_transfer,
    assert_ibc_transfer_flow,
    prepare_network,
    run_hermes_transfer,
)
from .utils import (
    ACCOUNTS,
    ADDRESS_PREFIX,
    ADDRS,
    DEFAULT_DENOM,
    KEYS,
    WETH_ADDRESS,
    assert_burn_tokenfactory_denom,
    assert_create_erc20_denom,
    assert_create_tokenfactory_denom,
    assert_mint_tokenfactory_denom,
    assert_tf_flow,
    assert_transfer_tokenfactory_denom,
    build_and_deploy_contract_async,
    build_contract,
    denom_to_erc20_address,
    derive_new_account,
    escrow_address,
    eth_to_bech32,
    generate_isolated_address,
    send_transaction_async,
    wait_for_balance_change,
)

pytestmark = pytest.mark.slow

PRECOMPILE = Contract(build_contract("ICS20I")["abi"])
ICS20 = "0x0000000000000000000000000000000000000802"
gas = 400_000


@pytest.fixture(scope="module")
def ibc(request, tmp_path_factory):
    "prepare-network"
    name = "ibc"
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp(name)
    yield from prepare_network(path, name, chain)


async def assert_tokenfactory_flow(cli, w3, signer1, receiver):
    subdenom = "test"
    gas = 300000
    tf_amt = 10**6
    transfer_amt = 1
    burn_amt = 10**3
    addr_signer1 = eth_to_bech32(signer1)
    addr_receiver = eth_to_bech32(receiver)
    tf_denom = assert_create_tokenfactory_denom(
        cli, subdenom, _from=addr_signer1, gas=620000
    )
    tf_erc20_addr = denom_to_erc20_address(tf_denom)
    assert (await ERC20.fns.decimals().call(w3, to=tf_erc20_addr)) == 0
    total = await ERC20.fns.totalSupply().call(w3, to=tf_erc20_addr)
    signer1_balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    balance = cli.balance(addr_signer1, tf_denom)
    assert total == balance == signer1_balance_eth == 0

    balance = assert_mint_tokenfactory_denom(
        cli, tf_denom, tf_amt, _from=addr_signer1, gas=gas
    )
    signer1_balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    total = await ERC20.fns.totalSupply().call(w3, to=tf_erc20_addr)
    assert total == balance == signer1_balance_eth == tf_amt

    balance = assert_transfer_tokenfactory_denom(
        cli, tf_denom, addr_receiver, transfer_amt, _from=addr_signer1, gas=gas
    )
    signer1_balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    assert balance == signer1_balance_eth == tf_amt - transfer_amt

    balance = assert_burn_tokenfactory_denom(
        cli, tf_denom, burn_amt, _from=addr_signer1, gas=gas
    )
    signer1_balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    assert balance == signer1_balance_eth == tf_amt - transfer_amt - burn_amt

    balance = cli.balance(addr_receiver, tf_denom)
    signer1_balance_eth = await ERC20.fns.balanceOf(receiver).call(w3, to=tf_erc20_addr)
    assert balance == signer1_balance_eth == transfer_amt
    return tf_denom, tf_erc20_addr


async def wait_for_balance_change_async(
    w3: AsyncWeb3, addr, token_addr: str, init_balance: int
):
    async def check_balance():
        current_balance = await ERC20.fns.balanceOf(addr).call(w3, to=token_addr)
        return current_balance if current_balance != init_balance else None

    return await wait_for_fn_async("balance change", check_balance)


async def test_ibc_transfer(ibc):
    w3 = ibc.ibc1.async_w3
    cli = ibc.ibc1.cosmos_cli()
    cli2 = ibc.ibc2.cosmos_cli()
    signer1 = ADDRS["signer1"]
    signer2 = ADDRS["signer2"]
    addr_signer2 = eth_to_bech32(signer2)
    addr_signer1 = eth_to_bech32(signer1)
    ibc_erc20_addr = await assert_ibc_transfer_flow(
        ibc,
        chain2_denom=DEFAULT_DENOM,
        chain2_prefix=ADDRESS_PREFIX,
        return_ratio=0.5,
    )
    receiver = derive_new_account(4).address

    await assert_tf_flow(w3, receiver, signer1, signer2, ibc_erc20_addr)
    # check create mint transfer and burn tokenfactory denom
    tf_denom, tf_erc20_addr = await assert_tokenfactory_flow(cli, w3, signer1, receiver)

    transfer_amt = 50
    print(f"chain1 signer1 -> chain2 signer2 {transfer_amt}{tf_denom}")
    dst_denom, signer2_balance = assert_hermes_transfer(
        ibc.hermes,
        cli,
        "signer1",
        transfer_amt,
        cli2,
        addr_signer2,
        denom=tf_denom,
    )

    print("mm-signer2_balance", signer2_balance)
    print(f"chain2 signer2 -> chain1 signer1 {transfer_amt}{dst_denom}")
    balance_bf = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    assert balance_bf == cli.balance(addr_signer1, tf_denom)
    run_hermes_transfer(
        ibc.hermes,
        cli2,
        "signer2",
        transfer_amt,
        cli,
        addr_signer1,
        denom=dst_denom,
    )
    assert cli2.balance(addr_signer2, dst_denom) == signer2_balance - transfer_amt
    balance_af = await wait_for_balance_change_async(
        w3, signer1, tf_erc20_addr, balance_bf
    )
    assert (
        balance_af == cli.balance(addr_signer1, tf_denom) == balance_bf + transfer_amt
    )
    assert cli2.balance(addr_signer2, dst_denom) == 0

    print(f"ibc precompile: chain1 signer1 -> chain2 signer2 {transfer_amt}{tf_denom}")
    timeout_height = (0, 0)
    # timeout in nanoseconds - current time + 10 minutes
    timeout_timestamp = int((time.time() + 600) * 10**9)
    balance_bf = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    signer2_balance_bf = cli2.balance(addr_signer2, dst_denom)
    res = await PRECOMPILE.fns.transfer(
        "transfer",
        "channel-0",
        tf_denom,
        transfer_amt,
        signer1,
        addr_signer2,
        timeout_height,
        timeout_timestamp,
        "",
    ).transact(w3, ACCOUNTS["signer1"], to=ICS20, gas=gas)
    assert res.status == 1
    sequence = int.from_bytes(res.logs[0].data, "big")
    assert sequence > 0

    balance_af = await wait_for_balance_change_async(
        w3, signer1, tf_erc20_addr, balance_bf
    )
    assert balance_af == balance_bf - transfer_amt
    dst_balance = wait_for_balance_change(
        cli2, addr_signer2, dst_denom, signer2_balance_bf
    )
    assert dst_balance == signer2_balance_bf + transfer_amt


async def prepare_dest_callback(w3, sender, amt):
    # deploy cb contract
    contract = await build_and_deploy_contract_async(
        w3, "CounterWithCallbacks", key=KEYS["signer1"]
    )
    calldata = await contract.functions.add(WETH_ADDRESS, amt).build_transaction(
        {"from": sender, "gas": 210000}
    )
    calldata = calldata["data"][2:]
    dest_cb = {
        "dest_callback": {
            "address": contract.address,
            "gas_limit": "1000000",
            "calldata": calldata,
        }
    }
    return contract.address, json.dumps(dest_cb)


async def prepare_src_callback(w3, funder_name: str, amt: int):
    contract = await build_and_deploy_contract_async(
        w3, "CounterWithCallbacks", key=KEYS[funder_name]
    )
    cb_balance_bf = await ERC20.fns.balanceOf(contract.address).call(
        w3, to=WETH_ADDRESS
    )
    receipt = await ERC20.fns.transfer(contract.address, amt).transact(
        w3, ACCOUNTS[funder_name], to=WETH_ADDRESS, gas=gas
    )
    assert receipt["status"] == 1
    await wait_for_balance_change_async(
        w3, contract.address, WETH_ADDRESS, cb_balance_bf
    )
    # send from contract via ICS20 with src_callback memo pointing to itself.
    src_cb = {
        "src_callback": {
            "address": contract.address,
            "gas_limit": "1000000",
        }
    }
    return contract, json.dumps(src_cb)


async def test_ibc_cb(ibc):
    w3 = ibc.ibc1.async_w3
    cli = ibc.ibc1.cosmos_cli()
    cli2 = ibc.ibc2.cosmos_cli()
    signer1 = ADDRS["signer1"]
    signer2 = ADDRS["signer2"]
    addr_signer2 = eth_to_bech32(signer2)
    erc20_denom, total = await assert_create_erc20_denom(w3, signer1)

    # check native erc20 transfer
    res = cli.register_erc20(WETH_ADDRESS, _from="community", gas=400_000)
    assert res["code"] == 0
    erc20_denom = f"erc20:{WETH_ADDRESS}"
    res = cli.query_erc20_token_pair(erc20_denom)
    assert res["erc20_address"] == WETH_ADDRESS, res

    transfer_amt = total // 2
    print(f"chain1 signer1 -> chain2 signer2 {transfer_amt}{erc20_denom}")
    port = "transfer"
    channel = "channel-0"
    isolated = generate_isolated_address(channel, addr_signer2)

    dst_denom, signer2_balance = assert_hermes_transfer(
        ibc.hermes,
        cli,
        "signer1",
        transfer_amt,
        cli2,
        addr_signer2,
        denom=erc20_denom,
        skip_src_balance_check=True,
    )

    signer1_balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=WETH_ADDRESS)
    assert signer1_balance_eth == total - transfer_amt

    # deploy cb contract
    transfer_amt = total // 2
    cb_contract, dest_cb = await prepare_dest_callback(w3, signer1, transfer_amt)
    cb_balance_bf = await ERC20.fns.balanceOf(cb_contract).call(w3, to=WETH_ADDRESS)

    print(f"chain2 signer2 -> chain1 signer1 {transfer_amt}{dst_denom}")
    run_hermes_transfer(
        ibc.hermes,
        cli2,
        "signer2",
        transfer_amt,
        cli,
        isolated,
        denom=dst_denom,
        memo=dest_cb,
    )
    assert cli2.balance(addr_signer2, dst_denom) == signer2_balance - transfer_amt
    cb_balance = await wait_for_balance_change_async(
        w3, cb_contract, WETH_ADDRESS, cb_balance_bf
    )
    assert cb_balance == cb_balance_bf + transfer_amt
    escrow_addr = escrow_address(port, channel)
    assert cli.balance(escrow_addr, erc20_denom) == 0
    assert cli2.balance(addr_signer2, dst_denom) == 0


async def test_ibc_src_ack_callback(ibc):
    w3 = ibc.ibc2.async_w3
    cli = ibc.ibc2.cosmos_cli()
    signer2 = ADDRS["signer2"]

    erc20_denom, total = await assert_create_erc20_denom(w3, signer2)

    res = cli.register_erc20(WETH_ADDRESS, _from="community", gas=400_000)
    assert res["code"] == 0, res

    send_amt = total // 10
    cb, src_cb_memo = await prepare_src_callback(w3, "signer2", send_amt)

    addr_signer1 = eth_to_bech32(ADDRS["signer1"])
    timeout_height = (0, 0)
    timeout_timestamp = int((time.time() + 600) * 10**9)

    tx = await cb.functions.ibcTransfer(
        "transfer",
        "channel-0",
        erc20_denom,
        send_amt,
        addr_signer1,
        timeout_height,
        timeout_timestamp,
        src_cb_memo,
    ).build_transaction({"from": signer2, "gas": 900_000})

    txreceipt = await send_transaction_async(w3, ACCOUNTS["signer2"], **tx)
    assert txreceipt["status"] == 1

    # ack callback increments counter on the source contract
    async def check_ack():
        val = await cb.functions.counter().call()
        return val if val >= 1 else None

    ack_counter = await wait_for_fn_async("ack callback", check_ack)
    assert ack_counter >= 1

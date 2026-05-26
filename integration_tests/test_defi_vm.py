import time

import pytest
from eth_contract.erc20 import ERC20
from hexbytes import HexBytes
from pydefi.vm import Program
from web3 import AsyncWeb3

from .ibc_utils import ibc_denom_hash, prepare_network
from .utils import (
    ACCOUNTS,
    ADDRS,
    WETH_ADDRESS,
    assert_create_erc20_denom,
    build_and_deploy_contract_async,
    eth_to_bech32,
    wait_for_balance_change,
)

pytestmark = pytest.mark.asyncio


async def deploy_vm(w3: AsyncWeb3):
    """Deploy the Analog-Labs interpreter + a fresh DeFiVM bound to it."""
    interp = await build_and_deploy_contract_async(w3, "Interpreter", via_ir=False)
    vm = await build_and_deploy_contract_async(w3, "DeFiVM", args=(interp.address,))
    return vm


@pytest.fixture(scope="module")
def ibc(request, tmp_path_factory):
    "prepare-network"
    name = "ibc"
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp(name)
    yield from prepare_network(path, name, chain)


async def test_flow(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    deployer = ACCOUNTS["community"]

    vm = await deploy_vm(w3)

    value_in = 10**15
    vm_before = await w3.eth.get_balance(vm.address)
    sender_before = await w3.eth.get_balance(deployer.address)

    # Onchain: assert the VM received `value_in`. Offchain: verify the
    # balance shift after the call returns.
    prog = Program()
    prog.assert_ge(
        prog.eth_balance(prog.builder.address()), value_in, "vm balance too low"
    )
    tx_hash = await vm.functions.execute(prog.build()).transact(
        {"from": deployer.address, "value": value_in}
    )
    receipt = await w3.eth.get_transaction_receipt(tx_hash)
    assert receipt["status"] == 1

    vm_after = await w3.eth.get_balance(vm.address)
    sender_after = await w3.eth.get_balance(deployer.address)
    gas_cost = receipt["effectiveGasPrice"] * receipt["gasUsed"]

    assert vm_after == vm_before + value_in
    assert sender_before - sender_after == value_in + gas_cost


async def test_ibc_cb(ibc):
    w3: AsyncWeb3 = ibc.ibc1.async_w3
    cli1 = ibc.ibc1.cosmos_cli()
    cli2 = ibc.ibc2.cosmos_cli()

    deployer = ACCOUNTS["community"]
    signer1 = ACCOUNTS["signer1"]
    addr_signer2 = eth_to_bech32(ADDRS["signer2"])

    erc20_denom, _ = await assert_create_erc20_denom(w3, signer1.address)
    res = cli1.register_erc20(WETH_ADDRESS, _from="community", gas=400_000)
    assert res["code"] == 0

    vm = await deploy_vm(w3)
    cb = await build_and_deploy_contract_async(w3, "CounterWithCallbacks")
    cb_addr = HexBytes(cb.address)

    channel_id = "channel-0"
    port_id = "transfer"
    sequence = 7
    payload = b"ibc_payload\x00hello\xff"
    acknowledgement = b'{"result":"ok","payload":true}'

    tx = await cb.functions.onPacketAcknowledgement(
        channel_id, port_id, sequence, payload, acknowledgement
    ).build_transaction({"from": deployer.address, "gas": 300_000})
    calldata = bytes.fromhex(tx["data"][2:])

    # DeFiVM-mediated call to onPacketAcknowledgement; require success.
    prog = Program()
    ok = prog.call_raw(cb_addr, calldata, gas=300_000)
    prog.assert_(ok)
    exec_tx = await vm.functions.execute(prog.build()).transact(
        {"from": deployer.address}
    )
    exec_receipt = await w3.eth.get_transaction_receipt(exec_tx)
    assert exec_receipt["status"] == 1

    assert await cb.functions.counter().call() == 1

    callback_logs = cb.events.PacketAcknowledged().process_receipt(exec_receipt)
    assert len(callback_logs) == 1
    event_args = callback_logs[0]["args"]
    assert event_args["channelId"] == w3.keccak(text=channel_id)
    assert event_args["portId"] == w3.keccak(text=port_id)
    assert event_args["sequence"] == sequence
    assert event_args["data"] == payload
    assert event_args["acknowledgement"] == acknowledgement

    send_amt = 10
    cb_balance_base = await ERC20.fns.balanceOf(cb.address).call(w3, to=WETH_ADDRESS)
    fund_receipt = await ERC20.fns.transfer(cb.address, send_amt).transact(
        w3, signer1, to=WETH_ADDRESS
    )
    assert fund_receipt["status"] == 1

    timeout_height = (0, 0)
    timeout_timestamp = int((time.time() + 600) * 10**9)
    ibc_tx = await cb.functions.ibcTransfer(
        "transfer",
        "channel-0",
        erc20_denom,
        send_amt,
        addr_signer2,
        timeout_height,
        timeout_timestamp,
        "",
    ).build_transaction({"from": deployer.address, "gas": 900_000})
    ibc_calldata = bytes.fromhex(ibc_tx["data"][2:])

    dst_denom = f"ibc/{ibc_denom_hash(f'transfer/channel-0/{erc20_denom}')}"
    dst_balance_bf = cli2.balance(addr_signer2, dst_denom)

    # DeFiVM-mediated cross-chain transfer.
    prog = Program()
    ok = prog.call_raw(cb_addr, ibc_calldata, gas=900_000)
    prog.assert_(ok)
    tx_hash = await vm.functions.execute(prog.build()).transact(
        {"from": deployer.address}
    )
    receipt = await w3.eth.get_transaction_receipt(tx_hash)
    assert receipt["status"] == 1

    cb_balance_af = await ERC20.fns.balanceOf(cb.address).call(w3, to=WETH_ADDRESS)
    assert cb_balance_af == cb_balance_base

    dst_balance_af = wait_for_balance_change(
        cli2, addr_signer2, dst_denom, dst_balance_bf
    )
    assert dst_balance_af == dst_balance_bf + send_amt

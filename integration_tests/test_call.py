import asyncio
import base64
import io
import json
from contextlib import redirect_stdout
from typing import Iterable, Unpack

import pyrevm
import pytest
from eth_contract.erc20 import ERC20
from eth_contract.slots import parse_balance_slot, parse_supply_slot
from eth_contract.utils import ZERO_ADDRESS
from hexbytes import HexBytes
from web3 import Web3
from web3._utils.contracts import encode_transaction_data
from web3.types import TxParams

from .cosmostx_utils import Metadata
from .utils import (
    ADDRS,
    Contract,
    Greeter,
    assert_create_tokenfactory_denom,
    assert_mint_tokenfactory_denom,
    build_and_deploy_contract_async,
    denom_to_erc20_address,
)


def test_temporary_contract_code(mantra):
    state = 100
    w3: Web3 = mantra.w3
    greeter = Greeter("Greeter")
    data = encode_transaction_data(w3, "intValue", greeter.abi, args=[], kwargs={})
    # call an arbitrary address
    address = w3.to_checksum_address("0x0000000000000000000000000000ffffffffffff")
    hex_state = f"0x{HexBytes(w3.codec.encode(('uint256',), (state,))).hex()}"
    overrides = {
        address: {
            "code": greeter.code,
            "state": {
                ("0x" + "0" * 64): hex_state,
            },
        },
    }
    result = w3.eth.call(
        {
            "to": address,
            "data": data,
        },
        "latest",
        overrides,
    )
    assert (state,) == w3.codec.decode(("uint256",), result)


def test_override_state(mantra):
    w3: Web3 = mantra.w3
    greeter = Greeter("Greeter")
    greeter.deploy(w3)
    contract = greeter.contract
    assert contract.functions.greet().call() == "Hello"
    assert contract.functions.intValue().call() == 0

    int_value = 100
    hex_state = "0x" + HexBytes(w3.codec.encode(("uint256",), (int_value,))).hex()
    state = {("0x" + "0" * 64): hex_state}

    def call(fn_name, state_type="stateDiff"):
        data = encode_transaction_data(w3, fn_name, greeter.abi, args=[], kwargs={})
        return w3.eth.call(
            {"to": contract.address, "data": data},
            "latest",
            {contract.address: {state_type: state}},
        )

    result = call("intValue")
    assert w3.codec.decode(("uint256",), result) == (int_value,)
    # stateDiff don't affect the other state slots
    result = call("greet")
    assert w3.codec.decode(("string",), result) == ("Hello",)
    # state will overrides the whole state
    result = call("greet", state_type="state")
    assert w3.codec.decode(("string",), result) == ("",)


def trace_call(vm: pyrevm.EVM, **tx: Unpack[TxParams]) -> Iterable[dict]:
    """
    Capture and parse traces from a pyrevm message call.
    """
    with redirect_stdout(io.StringIO()) as out:
        vm.message_call(
            caller=tx.get("from", ZERO_ADDRESS),
            to=tx.get("to", ""),
            calldata=tx.get("data"),
            value=tx.get("value", 0),
        )

        out.seek(0)
    for line in out.readlines():
        yield json.loads(line)


@pytest.mark.asyncio
async def test_override_erc20_state(mantra):
    w3 = mantra.async_w3
    community = ADDRS["community"]
    contract = Contract("TestERC20A")
    contract.deploy(mantra.w3)
    address = contract.contract.address

    balance_fn = ERC20.fns.balanceOf(community)
    name_fn = ERC20.fns.name()
    symbol_fn = ERC20.fns.symbol()
    total_fn = ERC20.fns.totalSupply()

    total = await total_fn.call(w3, to=address)
    new_total = 1
    new_balance = total - 1

    vm = pyrevm.EVM(fork_url=mantra.w3_http_endpoint(), tracing=True, with_memory=True)

    def state_key(fn_data, parse_slot, *args):
        traces = trace_call(vm, to=address, data=fn_data)
        slot = parse_slot(HexBytes(address), *args, traces)
        return f"0x{slot.value(*args).slot.hex()}" if args else f"0x{slot.slot.hex()}"

    def state_value(value):
        return "0x" + HexBytes(w3.codec.encode(("uint256",), (value,))).hex()

    state = {
        state_key(total_fn.data, parse_supply_slot): state_value(new_total),
        state_key(
            balance_fn.data, parse_balance_slot, HexBytes(community)
        ): state_value(new_balance),
    }

    async def call(fn, state_type):
        return await fn.call(
            w3, to=address, state_override={address: {state_type: state}}
        )

    for state_type in ["stateDiff", "state"]:
        assert await call(balance_fn, state_type) == new_balance
        assert await call(total_fn, state_type) == new_total
        if state_type == "stateDiff":
            assert await call(name_fn, state_type) == await call(name_fn, "")
            assert await call(symbol_fn, state_type) == await call(symbol_fn, "")
        else:
            assert await call(name_fn, state_type) == ""
            assert await call(symbol_fn, state_type) == ""


def encode_key(prefix_byte, addr_bytes=None, denom=""):
    denom_bytes = denom.encode("utf-8")
    prefix = bytes([prefix_byte])
    if addr_bytes is not None:
        addr_len = bytes([len(addr_bytes)])
        key = prefix + addr_len + addr_bytes + denom_bytes
    else:
        key = prefix + denom_bytes
    return base64.b64encode(key).decode()


def encode_value(value):
    return base64.b64encode(value).decode()


async def test_override_precompile_state(mantra):
    w3, cli = mantra.async_w3, mantra.cosmos_cli()
    community = ADDRS["community"]
    sender = cli.address("community")
    subdenom = "eth_call"
    amt = 10**6

    denom = assert_create_tokenfactory_denom(cli, subdenom, _from=sender, gas=620000)
    address = denom_to_erc20_address(denom)
    assert_mint_tokenfactory_denom(cli, denom, amt, _from=sender, gas=320000)

    balance_fn = ERC20.fns.balanceOf(community)
    total_fn = ERC20.fns.totalSupply()
    name_fn = ERC20.fns.name()
    symbol_fn = ERC20.fns.symbol()

    balance, total = await asyncio.gather(
        balance_fn.call(w3, to=address),
        total_fn.call(w3, to=address),
    )
    assert balance == total == amt

    new_total = 1
    new_balance = 99
    metadata = Metadata(name="", symbol="").SerializeToString()
    meta_entry = {
        "key": encode_key(1, denom=denom),
        "value": encode_value(metadata),
        "delete": False,
    }
    addr_bytes = bytes.fromhex(community[2:])
    entries = [
        {
            "key": encode_key(0, denom=denom),
            "value": encode_value(str(new_total).encode()),
            "delete": False,
        },
        {
            "key": encode_key(2, addr_bytes, denom),
            "value": encode_value(str(new_balance).encode()),
            "delete": False,
        },
    ]
    diff0 = [{"name": "bank", "entries": entries}]
    diff1 = [{"name": "bank", "entries": entries + [meta_entry]}]

    async def call(fn, state_type):
        diff = diff0 if state_type == "stateDiff" else diff1
        return await fn.call(
            w3,
            to=address,
            state_override={
                address: {state_type: encode_value(json.dumps(diff).encode())}
            },
        )

    for state_type in ["stateDiff", "state"]:
        balance_res, total_res, name_res, symbol_res, name_orig, symbol_orig = (
            await asyncio.gather(
                call(balance_fn, state_type),
                call(total_fn, state_type),
                call(name_fn, state_type),
                call(symbol_fn, state_type),
                call(name_fn, ""),
                call(symbol_fn, ""),
            )
        )
        assert balance_res == new_balance
        assert total_res == new_total
        if state_type == "stateDiff":
            assert name_res == name_orig
            assert symbol_res == symbol_orig
        else:
            assert name_res == ""
            assert symbol_res == ""


async def test_dynamic_precompile_with_evm_override(mantra):
    w3, cli = mantra.async_w3, mantra.cosmos_cli()
    community = ADDRS["community"]
    sender = cli.address("community")
    subdenom = "evm_override_test"
    amt = 10**6

    denom = assert_create_tokenfactory_denom(cli, subdenom, _from=sender, gas=620000)
    address = denom_to_erc20_address(denom)
    assert_mint_tokenfactory_denom(cli, denom, amt, _from=sender, gas=320000)

    balance_fn = ERC20.fns.balanceOf(community)
    # precompile works without any overrides
    assert await balance_fn.call(w3, to=address) == amt

    # use EVM state override on an unrelated address for GetPrecompileRecipientCallHook
    dummy_addr = w3.to_checksum_address("0x0000000000000000000000000000ffffffffffff")
    state_override = {dummy_addr: {"balance": hex(10**18)}}

    # dynamic precompile should still work with EVM overrides active
    assert (await balance_fn.call(w3, to=address, state_override=state_override)) == amt


@pytest.mark.connect
async def test_connect_opcode(connect_mantra):
    await test_opcode(None, connect_mantra)


@pytest.mark.asyncio
async def test_opcode(mantra, connect_mantra):
    contract = await build_and_deploy_contract_async(connect_mantra.async_w3, "Random")
    res = await contract.caller.randomTokenId()
    assert res > 0, res

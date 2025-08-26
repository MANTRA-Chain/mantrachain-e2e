import pytest
from hexbytes import HexBytes
from web3 import Web3
from web3._utils.contracts import encode_transaction_data

from .utils import Greeter, build_and_deploy_contract_async


@pytest.mark.skip(reason="skipping temporary_contract_code test")
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


@pytest.mark.skip(reason="skipping override_state test")
def test_override_state(mantra):
    w3: Web3 = mantra.w3
    greeter = Greeter("Greeter")
    greeter.deploy(w3)
    contract = greeter.contract
    assert "Hello" == contract.functions.greet().call()
    assert 0 == contract.functions.intValue().call()

    int_value = 100
    hex_state = f"0x{HexBytes(w3.codec.encode(('uint256',), (int_value,))).hex()}"
    state = {
        ("0x" + "0" * 64): hex_state,
    }
    data = encode_transaction_data(w3, "intValue", greeter.abi, args=[], kwargs={})
    result = w3.eth.call(
        {
            "to": contract.address,
            "data": data,
        },
        "latest",
        {
            contract.address: {
                "code": greeter.code,
                "stateDiff": state,
            },
        },
    )
    assert (int_value,) == w3.codec.decode(("uint256",), result)

    # stateDiff don't affect the other state slots
    data = encode_transaction_data(w3, "greet", greeter.abi, args=[], kwargs={})
    result = w3.eth.call(
        {
            "to": contract.address,
            "data": data,
        },
        "latest",
        {
            contract.address: {
                "to": contract.address,
                "stateDiff": state,
            },
        },
    )
    assert ("Hello",) == w3.codec.decode(("string",), result)

    # state will overrides the whole state
    data = encode_transaction_data(w3, "greet", greeter.abi, args=[], kwargs={})
    result = w3.eth.call(
        {
            "to": contract.address,
            "data": data,
        },
        "latest",
        {
            contract.address: {
                "to": contract.address,
                "state": state,
            },
        },
    )
    assert ("",) == w3.codec.decode(("string",), result)


@pytest.mark.asyncio
async def test_opcode(mantra):
    contract = await build_and_deploy_contract_async(mantra.async_w3, "Random")
    res = await contract.caller.randomTokenId()
    assert res > 0, res

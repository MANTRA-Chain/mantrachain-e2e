import pytest
import web3

from .utils import (
    ACCOUNTS,
    ADDRS,
    build_and_deploy_contract_async,
)
from .utils import send_transaction_async as send_transaction
from .utils import (
    w3_wait_for_new_blocks_async,
)

pytestmark = pytest.mark.asyncio

# 2048 non-zero calldata bytes. Per EIP-7623 the floor is
# 21000 + 10 * 4 * non_zero_bytes; the intrinsic cost is 21000 + 16 * bytes
# so the floor strictly exceeds intrinsic + a value-transfer to an EOA.
EIP7623_DATA = b"\x01" * 2048
EIP7623_FLOOR = 21000 + 10 * 4 * len(EIP7623_DATA)  # 102_920

BURN_GAS_CONTRACT = None


async def get_burn_gas_contract(w3):
    global BURN_GAS_CONTRACT
    if BURN_GAS_CONTRACT is None:
        BURN_GAS_CONTRACT = await build_and_deploy_contract_async(w3, "BurnGas")
    return BURN_GAS_CONTRACT


async def test_gas_call(mantra):
    w3 = mantra.async_w3
    input = 10
    contract = await get_burn_gas_contract(w3)
    txhash = await contract.functions.burnGas(input).transact(
        {"from": ADDRS["community"], "gasPrice": await w3.eth.gas_price}
    )
    receipt = await w3.eth.wait_for_transaction_receipt(txhash)
    assert receipt.gasUsed == 267649


async def _send_eip7623_tx(w3, gas: int):
    tx = {
        "to": ADDRS["signer1"],
        "value": 1,
        "data": EIP7623_DATA,
        "gas": gas,
    }
    return await send_transaction(w3, ACCOUNTS["community"], **tx)


async def test_eip7623_floor_data_gas_is_charged(mantra):
    """Calldata-heavy EOA transfer is charged at least the EIP-7623 floor."""
    receipt = await _send_eip7623_tx(mantra.async_w3, gas=200_000)
    assert (
        receipt.gasUsed >= EIP7623_FLOOR
    ), f"gasUsed={receipt.gasUsed} below floor={EIP7623_FLOOR}"


async def test_eip7623_below_floor_is_rejected(mantra):
    """gasLimit below the EIP-7623 floor is rejected."""
    with pytest.raises(web3.exceptions.Web3RPCError, match="floor data gas"):
        await _send_eip7623_tx(mantra.async_w3, gas=EIP7623_FLOOR - 1)


async def test_block_gas_limit(mantra):
    w3 = mantra.async_w3
    # get the block gas limit from the latest block
    await w3_wait_for_new_blocks_async(w3, 5)
    block = await w3.eth.get_block("latest")
    exceeded_gas_limit = block.gasLimit + 100

    # send a transaction exceeding the block gas limit
    gas_price = await w3.eth.gas_price
    value = 10
    tx = {
        "to": ADDRS["signer1"],
        "value": value,
        "gas": exceeded_gas_limit,
        "gasPrice": gas_price,
    }
    # expect an error due to the block gas limit
    msg = "exceeds block gas limit"
    sender = ADDRS["community"]
    with pytest.raises(web3.exceptions.Web3RPCError, match=msg):
        await send_transaction(w3, sender, False, **tx)

    # expect an error on contract call due to block gas limit
    with pytest.raises(web3.exceptions.Web3RPCError, match=msg):
        contract = await get_burn_gas_contract(w3)
        await contract.functions.burnGas(exceeded_gas_limit).transact(
            {
                "from": sender,
                "gas": exceeded_gas_limit,
                "gasPrice": gas_price,
            }
        )

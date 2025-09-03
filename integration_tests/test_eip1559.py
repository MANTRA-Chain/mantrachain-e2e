import pytest
from eth_contract.utils import send_transaction

from .utils import (
    ACCOUNTS,
    ADDRS,
    adjust_base_fee,
    w3_wait_for_block_async,
)

pytestmark = pytest.mark.asyncio


@pytest.mark.connect
async def test_connect_dynamic_fee_tx(connect_mantra):
    await test_dynamic_fee_tx(None, connect_mantra, update_params=False)


async def test_dynamic_fee_tx(mantra, connect_mantra, update_params=True):
    """
    test basic eip-1559 tx works:
    - tx fee calculation is compliant to go-ethereum
    - base fee adjustment is compliant to go-ethereum
    """
    w3 = connect_mantra.async_w3
    amount = 1000
    before = await w3.eth.get_balance(ADDRS["community"])
    tip_price = 10000000000
    max_price = 1000000000000 + tip_price
    begin = await w3.eth.block_number
    await w3_wait_for_block_async(w3, begin + 1)
    tx = {
        "to": "0x0000000000000000000000000000000000000000",
        "value": amount,
        "gas": 21000,
        "maxFeePerGas": max_price,
        "maxPriorityFeePerGas": tip_price,
    }
    txreceipt = await send_transaction(w3, ACCOUNTS["community"], **tx)
    blk = await w3.eth.get_block(txreceipt.blockNumber)
    assert txreceipt.effectiveGasPrice == blk.baseFeePerGas + tip_price

    fee_expected = txreceipt.gasUsed * txreceipt.effectiveGasPrice
    after = await w3.eth.get_balance(ADDRS["community"])
    fee_deducted = before - after - amount
    assert fee_deducted == fee_expected

    assert blk.gasUsed == txreceipt.gasUsed  # we are the only tx in the block

    if not update_params:
        return

    # check the next block's base fee is adjusted accordingly
    await w3_wait_for_block_async(w3, txreceipt.blockNumber + 1)
    next_base_price = (await w3.eth.get_block(txreceipt.blockNumber + 1)).baseFeePerGas
    params = mantra.cosmos_cli().get_params("feemarket")["params"]
    assert (
        abs(
            next_base_price
            - adjust_base_fee(blk.baseFeePerGas, blk.gasLimit, blk.gasUsed, params)
        )
        <= 1
    )


@pytest.mark.connect
async def test_connect_base_fee_adjustment(connect_mantra):
    await test_base_fee_adjustment(None, connect_mantra, update_params=False)


async def test_base_fee_adjustment(mantra, connect_mantra, update_params=True):
    """
    verify base fee adjustment of three continuous empty blocks
    """
    w3 = connect_mantra.async_w3
    begin = await w3.eth.block_number
    await w3_wait_for_block_async(w3, begin + 3)

    if not update_params:
        return

    blk = await w3.eth.get_block(begin)
    parent_fee = blk.baseFeePerGas
    params = mantra.cosmos_cli().get_params("feemarket")["params"]

    for i in range(3):
        fee = (await w3.eth.get_block(begin + 1 + i)).baseFeePerGas
        assert abs(fee - adjust_base_fee(parent_fee, blk.gasLimit, 0, params)) <= 1
        parent_fee = fee


@pytest.mark.connect
async def test_connect_recommended_fee_per_gas(connect_mantra):
    await test_recommended_fee_per_gas(None, connect_mantra)


async def test_recommended_fee_per_gas(mantra, connect_mantra):
    """The recommended base fee per gas returned by eth_gasPrice is
    base fee of the block just produced + eth_maxPriorityFeePerGas (the buffer).\n
    Verify the calculation of recommended base fee per gas (eth_gasPrice)
    """
    w3 = connect_mantra.async_w3
    recommended_base_fee_per_gas = await w3.eth.gas_price
    latest_block = await w3.eth.get_block("latest")
    base_fee = latest_block["baseFeePerGas"]
    buffer_fee = await w3.eth.max_priority_fee

    assert recommended_base_fee_per_gas == base_fee + buffer_fee, (
        f"eth_gasPrice is not the {latest_block['number']} block's "
        "base fee plus eth_maxPriorityFeePerGas"
    )


@pytest.mark.connect
async def test_connect_gas_price_meets_next_base_fee(connect_mantra):
    await test_gas_price_meets_next_base_fee(None, connect_mantra)


async def test_gas_price_meets_next_base_fee(mantra, connect_mantra):
    """The recommended base fee per gas returned by eth_gasPrice should
    be bigger than or equal to the base fee per gas of the next block, \n
    otherwise the tx does not meet the requirement to be included in the next block.\n
    """
    w3 = connect_mantra.async_w3
    base_block = await w3.eth.block_number
    recommended_base_fee = await w3.eth.gas_price

    await w3_wait_for_block_async(w3, base_block + 1)
    next_block = await w3.eth.get_block(base_block + 1)
    assert recommended_base_fee >= next_block["baseFeePerGas"], (
        f"recommended base fee: {recommended_base_fee} is smaller than "
        f"next block {next_block['number']} base fee: {next_block['baseFeePerGas']}"
    )

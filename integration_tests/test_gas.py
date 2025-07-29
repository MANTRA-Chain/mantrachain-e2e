import time

import pytest
import web3
from eth_contract.utils import send_transaction

from .utils import ADDRS, CONTRACTS, deploy_contract_async, w3_wait_for_new_blocks_async

pytestmark = pytest.mark.asyncio


async def test_gas_call(mantra):
    w3 = mantra.async_w3
    input = 10
    contract = await deploy_contract_async(w3, CONTRACTS["BurnGas"])
    txhash = await contract.functions.burnGas(input).transact(
        {"from": ADDRS["validator"], "gasPrice": await w3.eth.gas_price}
    )
    receipt = await w3.eth.wait_for_transaction_receipt(txhash)
    time.sleep(2)
    assert receipt.gasUsed == 267426


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
        "to": ADDRS["community"],
        "value": value,
        "gas": exceeded_gas_limit,
        "gasPrice": gas_price,
    }
    # expect an error due to the block gas limit
    msg = "exceeds block gas limit"
    sender = ADDRS["validator"]
    with pytest.raises(web3.exceptions.Web3RPCError, match=msg):
        await send_transaction(w3, sender, False, **tx)

    # expect an error on contract call due to block gas limit
    with pytest.raises(web3.exceptions.Web3RPCError, match=msg):
        contract = await deploy_contract_async(w3, CONTRACTS["BurnGas"])
        await contract.functions.burnGas(exceeded_gas_limit).transact(
            {
                "from": sender,
                "gas": exceeded_gas_limit,
                "gasPrice": gas_price,
            }
        )

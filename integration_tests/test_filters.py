import pytest
import web3
from eth_contract.utils import send_transaction
from web3 import AsyncWeb3, Web3

from .utils import (
    ADDRS,
    CONTRACTS,
    deploy_contract_async,
    w3_wait_for_new_blocks_async,
)

pytestmark = pytest.mark.asyncio


@pytest.mark.skip(reason="fixed in evm is reverted")
async def test_get_logs_by_topic(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    contract = await deploy_contract_async(w3, CONTRACTS["Greeter"])
    topic = f"0x{Web3.keccak(text='ChangeGreeting(address,string)').hex()}"
    tx = await contract.functions.setGreeting("world").build_transaction()
    await send_transaction(w3, ADDRS["validator"], **tx)

    current = await w3.eth.block_number
    # invalid block ranges
    test_cases = [
        {"fromBlock": hex(2000), "toBlock": "latest", "address": [contract.address]},
        {"fromBlock": hex(2), "toBlock": hex(1), "address": [contract.address]},
        {
            "fromBlock": "earliest",
            "toBlock": hex(current + 200),
            "address": [contract.address],
        },
        {
            "fromBlock": hex(current + 20),
            "toBlock": hex(current + 200),
            "address": [contract.address],
        },
    ]
    invalid_block_msg = "invalid block range params"
    for params in test_cases:
        with pytest.raises(web3.exceptions.Web3RPCError, match=invalid_block_msg):
            await w3.eth.get_logs(params)

    # log exists
    logs = await w3.eth.get_logs({"topics": [topic]})
    assert len(logs) == 1
    assert logs[0]["address"] == contract.address

    # Wait and confirm log doesn't appear in new blocks
    await w3_wait_for_new_blocks_async(w3, 2)
    assert len(await w3.eth.get_logs({"topics": [topic]})) == 0

    previous = current
    current = await w3.eth.block_number
    # valid block ranges
    valid_cases = [
        {"fromBlock": "earliest", "toBlock": "latest", "address": [contract.address]},
        {
            "fromBlock": "earliest",
            "toBlock": hex(current),
            "address": [contract.address],
        },
        {
            "fromBlock": hex(previous),
            "toBlock": "latest",
            "address": [contract.address],
        },
        {
            "fromBlock": hex(previous),
            "toBlock": hex(current),
            "address": [contract.address],
        },
    ]
    for params in valid_cases:
        logs = await w3.eth.get_logs(params)
        assert len(logs) > 0


async def test_pending_transaction_filter(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    flt = await w3.eth.filter("pending")
    assert await flt.get_new_entries() == []
    tx = {"to": ADDRS["community"], "value": 1000}
    receipt = await send_transaction(w3, ADDRS["validator"], **tx)
    assert receipt.status == 1
    assert receipt["transactionHash"] in await flt.get_new_entries()


async def test_block_filter(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    flt = await w3.eth.filter("latest")
    # new blocks
    await w3_wait_for_new_blocks_async(w3, 1)
    tx = {"to": ADDRS["community"], "value": 1000}
    receipt = await send_transaction(w3, ADDRS["validator"], **tx)
    assert receipt.status == 1
    blocks = await flt.get_new_entries()
    assert len(blocks) >= 1


async def test_event_log_filter(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    mycontract = await deploy_contract_async(w3, CONTRACTS["Greeter"])
    assert "Hello" == await mycontract.caller.greet()
    current_height = hex(await w3.eth.get_block_number())
    event_filter = await mycontract.events.ChangeGreeting.create_filter(
        from_block=current_height
    )
    tx = await mycontract.functions.setGreeting("world").build_transaction()
    tx_receipt = await send_transaction(w3, ADDRS["validator"], **tx)
    log = mycontract.events.ChangeGreeting().process_receipt(tx_receipt)[0]
    assert log["event"] == "ChangeGreeting"
    new_entries = await event_filter.get_new_entries()
    assert len(new_entries) == 1
    assert new_entries[0] == log
    assert "world" == await mycontract.caller.greet()
    # without new txs since last call
    assert await event_filter.get_new_entries() == []
    assert await event_filter.get_all_entries() == new_entries
    # Uninstall
    assert await w3.eth.uninstall_filter(event_filter.filter_id)
    assert not await w3.eth.uninstall_filter(event_filter.filter_id)

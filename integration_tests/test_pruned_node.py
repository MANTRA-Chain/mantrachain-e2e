from pathlib import Path

import pytest
from eth_bloom import BloomFilter
from eth_contract.erc20 import ERC20
from eth_utils import big_endian_to_int
from hexbytes import HexBytes
from web3.datastructures import AttributeDict

from .network import setup_custom_mantra
from .utils import (
    ADDRS,
    EVM_CHAIN_ID,
    Contract,
    address_to_bytes32,
    sign_transaction,
    wait_for_new_blocks,
)


@pytest.fixture(scope="module")
def mantra(request, tmp_path_factory):
    """start-mantra
    params: enable_auto_deployment
    """
    chain = request.config.getoption("chain_config")
    yield from setup_custom_mantra(
        tmp_path_factory.mktemp("pruned"),
        26900,
        Path(__file__).parent / "configs/pruned-node.jsonnet",
        chain=chain,
    )


def test_pruned_node(mantra):
    """
    test basic json-rpc apis works in pruned node
    """
    w3 = mantra.w3
    contract = Contract("TestERC20A")
    contract.deploy(w3)
    erc20 = contract.contract
    sender = ADDRS["community"]
    receiver = ADDRS["signer1"]
    tx = erc20.functions.transfer(receiver, 10).build_transaction({"from": sender})
    nonce = w3.eth.get_transaction_count(sender)
    signed = sign_transaction(w3, tx)
    txhash = w3.eth.send_raw_transaction(signed.raw_transaction)
    exp_gas_used = 51437

    print("wait for prunning happens")
    wait_for_new_blocks(mantra.cosmos_cli(0), 10)

    print("wait for transaction receipt", txhash.hex())
    txreceipt = w3.eth.wait_for_transaction_receipt(txhash)
    assert txreceipt.gasUsed == exp_gas_used
    assert len(txreceipt.logs) == 1
    data = "0x000000000000000000000000000000000000000000000000000000000000000a"
    expect_log = {
        "address": erc20.address,
        "topics": [
            ERC20.events.Transfer.topic,
            address_to_bytes32(sender),
            address_to_bytes32(receiver),
        ],
        "data": HexBytes(data),
        "transactionIndex": 0,
        "logIndex": 0,
        "removed": False,
    }
    assert expect_log.items() <= txreceipt.logs[0].items()

    # check get_balance and eth_call don't work on pruned state
    with pytest.raises(Exception):
        w3.eth.get_balance(sender, block_identifier=txreceipt.blockNumber)
    with pytest.raises(Exception):
        erc20.caller(block_identifier=txreceipt.blockNumber).balanceOf(sender)

    # check block bloom
    block = w3.eth.get_block(txreceipt.blockNumber)
    assert "baseFeePerGas" in block
    assert block.miner == "0x0000000000000000000000000000000000000000"
    bloom = BloomFilter(big_endian_to_int(block.logsBloom))
    assert HexBytes(erc20.address) in bloom
    for topic in expect_log["topics"]:
        assert topic in bloom

    tx1 = w3.eth.get_transaction(txhash)
    tx2 = w3.eth.get_transaction_by_block(
        txreceipt.blockNumber, txreceipt.transactionIndex
    )
    exp_tx = AttributeDict(
        {
            "from": sender,
            "gas": exp_gas_used,
            "input": ERC20.fns.transfer(receiver, 10).data,
            "nonce": nonce,
            "to": erc20.address,
            "transactionIndex": 0,
            "value": 0,
            "type": 2,
            "accessList": [],
            "chainId": EVM_CHAIN_ID,
        }
    )
    assert tx1 == tx2
    for name in exp_tx.keys():
        assert tx1[name] == tx2[name] == exp_tx[name]

    print(
        w3.eth.get_logs(
            {"fromBlock": txreceipt.blockNumber, "toBlock": txreceipt.blockNumber}
        )
    )

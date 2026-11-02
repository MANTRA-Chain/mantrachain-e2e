import pytest
from eth_contract.erc20 import ERC20
from pystarport.utils import wait_for_new_blocks
from web3.datastructures import AttributeDict

from .network import setup_mantra
from .utils import (
    ADDRS,
    EVM_CHAIN_ID,
    Contract,
    assert_erc20_transfer_log,
    sign_transaction,
)


@pytest.fixture(scope="module")
def mantra(request, tmp_path_factory):
    yield from setup_mantra(request, tmp_path_factory, "pruned-node", 26900)


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
    amt = 10
    tx = erc20.functions.transfer(receiver, amt).build_transaction({"from": sender})
    nonce = w3.eth.get_transaction_count(sender)
    signed = sign_transaction(w3, tx)
    txhash = w3.eth.send_raw_transaction(signed.raw_transaction)
    exp_gas_used = 51278

    print("wait for prunning happens")
    wait_for_new_blocks(mantra.cosmos_cli(0), 10)

    print("wait for transaction receipt", txhash.hex())
    txreceipt = w3.eth.wait_for_transaction_receipt(txhash)
    assert txreceipt.gasUsed == exp_gas_used
    assert_erc20_transfer_log(w3, txreceipt, erc20.address, sender, receiver, amt)

    # check get_balance and eth_call don't work on pruned state
    with pytest.raises(Exception):
        w3.eth.get_balance(sender, block_identifier=txreceipt.blockNumber)
    with pytest.raises(Exception):
        erc20.caller(block_identifier=txreceipt.blockNumber).balanceOf(sender)

    block = w3.eth.get_block(txreceipt.blockNumber)
    assert "baseFeePerGas" in block
    assert block.miner == "0x0000000000000000000000000000000000000000"

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

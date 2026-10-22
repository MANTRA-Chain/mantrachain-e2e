from pathlib import Path

import pytest
from pystarport.utils import w3_wait_for_block, wait_for_new_blocks

from .network import setup_custom_mantra
from .utils import (
    ADDRS,
    KEYS,
    WEI_PER_DENOM,
    adjust_base_fee,
    send_transaction,
)


@pytest.fixture(
    scope="module",
    params=[
        ("min_gas_price_eq", 26500),
        ("min_gas_price", 26530),
        ("min_gas_price_lte", 26560),
    ],
    ids=["custom_mantra_eq", "custom_mantra", "custom_mantra_lte"],
)
def custom_cluster(request, tmp_path_factory):
    cfg, base_port = request.param
    yield from setup_custom_mantra(
        tmp_path_factory.mktemp(cfg.replace("_", "-")),
        base_port,
        Path(__file__).parent / f"configs/{cfg}.jsonnet",
        chain=request.config.getoption("chain_config"),
    )


def test_dynamic_fee_tx(custom_cluster):
    cli = custom_cluster.cosmos_cli()
    wait_for_new_blocks(cli, 1)
    w3 = custom_cluster.w3
    amount = 10000
    before = w3.eth.get_balance(ADDRS["community"])
    tip_price = 1000000
    max_price = 400000000000000 + tip_price
    tx = {
        "to": "0x0000000000000000000000000000000000000000",
        "value": amount,
        "gas": 21000,
        "maxFeePerGas": max_price,
        "maxPriorityFeePerGas": tip_price,
    }
    txreceipt = send_transaction(w3, tx, KEYS["community"])
    assert txreceipt.status == 1
    blk = w3.eth.get_block(txreceipt.blockNumber)
    assert txreceipt.effectiveGasPrice == blk.baseFeePerGas + tip_price

    fee_expected = txreceipt.gasUsed * txreceipt.effectiveGasPrice
    after = w3.eth.get_balance(ADDRS["community"])
    fee_deducted = before - after - amount
    assert fee_deducted == fee_expected

    assert blk.gasUsed == txreceipt.gasUsed  # we are the only tx in the block

    # check the next block's base fee is adjusted accordingly
    w3_wait_for_block(w3, txreceipt.blockNumber + 1)
    fee = w3.eth.get_block(txreceipt.blockNumber + 1).baseFeePerGas
    params = cli.get_params("feemarket")
    assert fee == adjust_base_fee(
        blk.baseFeePerGas, blk.gasLimit, blk.gasUsed, params
    ), fee


def test_base_fee_adjustment(custom_cluster):
    """
    verify base fee adjustment of three continuous empty blocks
    """
    cli = custom_cluster.cosmos_cli()
    wait_for_new_blocks(cli, 1)
    w3 = custom_cluster.w3
    begin = w3.eth.block_number
    w3_wait_for_block(w3, begin + 3)

    blk = w3.eth.get_block(begin)
    parent_fee = blk.baseFeePerGas
    params = cli.get_params("feemarket")

    for i in range(3):
        fee = w3.eth.get_block(begin + 1 + i).baseFeePerGas
        assert fee == adjust_base_fee(parent_fee, blk.gasLimit, 0, params)
        parent_fee = fee

    call = w3.provider.make_request
    res = call("eth_feeHistory", [2, "latest", []])["result"]["baseFeePerGas"]
    # nextBaseFee should align max with minGasPrice in eth_feeHistory
    min_gas_price = max(float(params.get("min_gas_price", 0)) * WEI_PER_DENOM, 1)
    assert all(fee == hex(int(min_gas_price)) for fee in res), res

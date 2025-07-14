from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest
from web3 import Web3

from .network import setup_custom_mantra
from .utils import (
    ADDRS,
    WEI_PER_UOM,
    adjust_base_fee,
    eth_to_bech32,
    module_address,
    send_transaction,
    submit_gov_proposal,
    w3_wait_for_block,
    w3_wait_for_new_blocks,
)

NEW_BASE_FEE = 10000000000


@pytest.fixture(scope="module")
def custom_mantra(tmp_path_factory):
    path = tmp_path_factory.mktemp("fee-history")
    yield from setup_custom_mantra(
        path, 26500, Path(__file__).parent / "configs/fee-history.jsonnet"
    )




@pytest.mark.skip(reason="skipping basic")
def test_basic(custom_mantra):
    w3: Web3 = custom_mantra.w3
    # need at least 5 blocks
    w3_wait_for_block(w3, 5)
    call = w3.provider.make_request
    tx = {"to": ADDRS["community"], "value": 10, "gasPrice": w3.eth.gas_price}
    send_transaction(w3, tx)
    size = 4
    # size of base fee + next fee
    max = size + 1
    # only 1 base fee + next fee
    min = 2
    method = "eth_feeHistory"
    field = "baseFeePerGas"
    percentiles = [100]
    height = w3.eth.block_number
    latest = dict(
        blocks=["latest", hex(height)],
        expect=max,
    )
    earliest = dict(
        blocks=["earliest", "0x0"],
        expect=min,
    )
    for tc in [latest, earliest]:
        res = []
        with ThreadPoolExecutor(len(tc["blocks"])) as exec:
            tasks = [
                exec.submit(call, method, [size, b, percentiles]) for b in tc["blocks"]
            ]
            res = [future.result()["result"][field] for future in as_completed(tasks)]
        assert len(res) == len(tc["blocks"])
        assert res[0] == res[1]
        assert len(res[0]) == tc["expect"]

    for x in range(max):
        i = x + 1
        fee_history = call(method, [size, hex(i), percentiles])
        # start to reduce diff on i <= size - min
        diff = size - min - i
        reduce = size - diff
        target = reduce if diff >= 0 else max
        res = fee_history["result"]
        assert len(res[field]) == target
        oldest = i + min - max
        assert res["oldestBlock"] == hex(oldest if oldest > 0 else 0)


@pytest.mark.skip(reason="skipping change")
def test_change(custom_mantra):
    w3: Web3 = custom_mantra.w3
    call = w3.provider.make_request
    tx = {"to": ADDRS["community"], "value": 10, "gasPrice": w3.eth.gas_price}
    send_transaction(w3, tx)
    size = 4
    method = "eth_feeHistory"
    field = "baseFeePerGas"
    percentiles = [100]
    for b in ["latest", hex(w3.eth.block_number)]:
        history0 = call(method, [size, b, percentiles])["result"][field]
        w3_wait_for_new_blocks(w3, 2, 0.1)
        history1 = call(method, [size, b, percentiles])["result"][field]
        if b == "latest":
            assert history1 != history0
        else:
            assert history1 == history0


@pytest.mark.skip(reason="skipping next")
def test_next(custom_mantra):
    w3: Web3 = custom_mantra.w3
    tx = {"to": ADDRS["community"], "value": 10, "gasPrice": w3.eth.gas_price}
    send_transaction(w3, tx)
    assert_histories(
        w3, custom_mantra.cosmos_cli(), w3.eth.block_number, percentiles=[100]
    )


@pytest.mark.skip(reason="skipping beyond head")
def test_beyond_head(custom_mantra):
    end = hex(0x7FFFFFFFFFFFFFFF)
    res = custom_mantra.w3.provider.make_request("eth_feeHistory", [4, end, []])
    msg = f"request beyond head block: requested {int(end, 16)}"
    assert msg in res["error"]["message"]


@pytest.mark.skip(reason="skipping percentiles")
def test_percentiles(custom_mantra):
    w3: Web3 = custom_mantra.w3
    call = w3.provider.make_request
    method = "eth_feeHistory"
    percentiles = [[-1], [101], [2, 1]]
    size = 4
    msg = "invalid reward percentile"
    with ThreadPoolExecutor(len(percentiles)) as exec:
        tasks = [exec.submit(call, method, [size, "latest", p]) for p in percentiles]
        result = [future.result() for future in as_completed(tasks)]
        assert all(msg in res["error"]["message"] for res in result)


def update_feemarket_param(node, tmp_path, new_multiplier=2, new_denominator=200000000):
    cli = node.cosmos_cli()
    p = cli.get_params("feemarket")["params"]
    new_base_fee = f"{NEW_BASE_FEE/WEI_PER_UOM}"
    p["base_fee"] = new_base_fee
    p["elasticity_multiplier"] = new_multiplier
    p["base_fee_change_denominator"] = new_denominator
    submit_gov_proposal(
        node,
        tmp_path,
        messages=[
            {
                "@type": "/cosmos.evm.feemarket.v1.MsgUpdateParams",
                "authority": eth_to_bech32(module_address("gov")),
                "params": p,
            }
        ],
    )
    p = cli.get_params("feemarket")["params"]
    assert float(p["base_fee"]) - float(new_base_fee) == 0
    assert p["elasticity_multiplier"] == new_multiplier
    assert p["base_fee_change_denominator"] == new_denominator


@pytest.mark.skip(reason="skipping test_concurrent")
def test_concurrent(custom_mantra, tmp_path):
    w3: Web3 = custom_mantra.w3
    tx = {"to": ADDRS["community"], "value": 10, "gasPrice": w3.eth.gas_price}
    # send multi txs, overlap happens with query with 2nd tx's block number
    send_transaction(w3, tx)
    receipt1 = send_transaction(w3, tx)
    b1 = receipt1.blockNumber
    send_transaction(w3, tx)
    call = w3.provider.make_request
    field = "baseFeePerGas"
    update_feemarket_param(custom_mantra, tmp_path)
    percentiles = []
    method = "eth_feeHistory"
    # big enough concurrent requests to trigger overwrite bug
    total = 10
    size = 2
    params = [size, hex(b1), percentiles]
    res = []
    with ThreadPoolExecutor(total) as exec:
        t = [exec.submit(call, method, params) for i in range(total)]
        res = [future.result()["result"][field] for future in as_completed(t)]
    assert all(sublist == res[0] for sublist in res), res


def assert_histories(w3, cli, blk, percentiles=[]):
    call = w3.provider.make_request
    method = "eth_feeHistory"
    field = "baseFeePerGas"
    expected = []
    blocks = []
    histories = []
    for i in range(3):
        b = blk + i
        blocks.append(b)
        history = tuple(call(method, [1, hex(b), percentiles])["result"][field])
        histories.append(history)
        w3_wait_for_new_blocks(w3, 1, 0.1)
    blocks.append(b + 1)

    for b in blocks:
        next_base_price = w3.eth.get_block(b).baseFeePerGas
        prev = b - 1
        blk = w3.eth.get_block(prev)
        base_fee = blk.baseFeePerGas
        params = cli.get_params("feemarket")["params"]
        res = adjust_base_fee(
            base_fee,
            blk.gasLimit,
            blk.gasUsed,
            params,
        )
        if abs(next_base_price - res) == 1:
            next_base_price = res
        elif next_base_price != NEW_BASE_FEE:
            assert next_base_price == res
        expected.append(hex(next_base_price))
    assert all(
        abs(int(a, 16) - int(exp_a, 16)) <= 1 and abs(int(b, 16) - int(exp_b, 16)) <= 1
        for (a, b), (exp_a, exp_b) in zip(histories, zip(expected, expected[1:]))
    )


@pytest.mark.skip(reason="skipping test_param_change")
def test_param_change(custom_mantra, tmp_path):
    w3 = custom_mantra.w3
    cli = custom_mantra.cosmos_cli()
    update_feemarket_param(custom_mantra, tmp_path)
    assert_histories(w3, cli, w3.eth.block_number)
    tx = {"to": ADDRS["community"], "value": 10, "gasPrice": w3.eth.gas_price}
    receipt = send_transaction(w3, tx)
    assert_histories(w3, cli, receipt.blockNumber)

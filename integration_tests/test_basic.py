import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
import web3
from eth_bloom import BloomFilter
from eth_contract.erc20 import ERC20
from eth_contract.utils import send_transaction as send_transaction_async
from eth_utils import big_endian_to_int
from hexbytes import HexBytes

from .utils import (
    ACCOUNTS,
    ADDRS,
    DEFAULT_DENOM,
    KEYS,
    Contract,
    Greeter,
    RevertTestContract,
    address_to_bytes32,
    assert_balance,
    assert_transfer,
    build_batch_tx,
    build_contract,
    contract_address,
    do_multisig,
    recover_community,
    send_transaction,
    transfer_via_cosmos,
    w3_wait_for_new_blocks,
)


@pytest.mark.connect
def test_connect_simple(connect_mantra, tmp_path):
    test_simple(None, connect_mantra, tmp_path, check_reserve=False)


def test_simple(mantra, connect_mantra, tmp_path, check_reserve=True):
    """
    check number of validators
    """
    cli = connect_mantra.cosmos_cli(tmp_path)
    assert len(cli.validators()) > 0
    if check_reserve:
        # check vesting account
        cli = mantra.cosmos_cli()
        denom = cli.get_params("evm")["params"]["evm_denom"]
        addr = cli.address("reserve")
        account = cli.account(addr)["account"]
        assert account["type"] == "/cosmos.vesting.v1beta1.DelayedVestingAccount"
        assert account["value"]["base_vesting_account"]["original_vesting"] == [
            {"denom": denom, "amount": "100000000000000000000"}
        ]


@pytest.mark.connect
def test_connect_transfer(connect_mantra, tmp_path):
    test_transfer(None, connect_mantra, tmp_path)


def test_transfer(mantra, connect_mantra, tmp_path):
    """
    check simple transfer tx success
    """
    cli = connect_mantra.cosmos_cli(tmp_path)
    addr_a = cli.address("community")
    addr_b = cli.address("reserve")
    assert_transfer(cli, addr_a, addr_b)


@pytest.mark.connect
async def test_connect_send_transaction(connect_mantra):
    await test_send_transaction(None, connect_mantra, check_gas=False)


async def test_send_transaction(mantra, connect_mantra, check_gas=True):
    tx = {"to": ADDRS["signer1"], "value": 1000}
    receipt = await send_transaction_async(
        connect_mantra.async_w3, ACCOUNTS["community"], **tx
    )
    if check_gas:
        assert receipt.gasUsed == 21000


@pytest.mark.connect
def test_connect_events(connect_mantra):
    test_events(None, connect_mantra, exp_gas_used=None)


def test_events(mantra, connect_mantra, exp_gas_used=806200):
    w3 = connect_mantra.w3
    sender = ADDRS["community"]
    receiver = ADDRS["signer1"]
    contract = Contract("TestERC20A")
    contract.deploy(w3, exp_gas_used=exp_gas_used)
    erc20 = contract.contract
    amt = 10
    tx = erc20.functions.transfer(receiver, amt).build_transaction({"from": sender})
    txreceipt = send_transaction(w3, tx)
    assert len(txreceipt.logs) == 1
    expect_log = {
        "address": erc20.address,
        "topics": [
            ERC20.events.Transfer.topic,
            address_to_bytes32(sender),
            address_to_bytes32(receiver),
        ],
        "data": HexBytes(amt.to_bytes(32, "big")),
        "transactionIndex": 0,
        "logIndex": 0,
        "removed": False,
    }
    assert expect_log.items() <= txreceipt.logs[0].items()

    # check block bloom
    bloom = BloomFilter(
        big_endian_to_int(w3.eth.get_block(txreceipt.blockNumber).logsBloom)
    )
    assert HexBytes(erc20.address) in bloom
    for topic in expect_log["topics"]:
        assert topic in bloom

    block_logs = w3.eth.get_block_receipts(txreceipt.blockNumber)[0].logs[0]
    call = w3.provider.make_request
    tx_logs = call("eth_getTransactionLogs", [txreceipt.transactionHash])["result"][0]
    for k in expect_log:
        assert expect_log[k] == block_logs[k]
        if k == "address":
            assert expect_log[k] == w3.to_checksum_address(tx_logs[k])
        elif k == "data":
            assert expect_log[k].hex() == block_logs[k].hex() == tx_logs[k][2:]
        elif k == "topics":
            assert expect_log[k] == [HexBytes(t) for t in tx_logs[k]]
        elif k in ("transactionIndex", "logIndex"):
            assert expect_log[k] == int(tx_logs[k], 16)
        else:
            assert expect_log[k] == tx_logs[k]


@pytest.mark.connect
async def test_connect_minimal_gas_price(connect_mantra):
    await test_minimal_gas_price(None, connect_mantra)


@pytest.mark.asyncio
async def test_minimal_gas_price(mantra, connect_mantra):
    w3 = connect_mantra.async_w3
    tx = {
        "to": "0x0000000000000000000000000000000000000000",
        "value": 10000,
        "gasPrice": 1,
    }
    with pytest.raises(web3.exceptions.Web3RPCError, match="insufficient fee"):
        await send_transaction_async(w3, ACCOUNTS["community"], **tx)
    tx["gasPrice"] = await w3.eth.gas_price
    receipt = await send_transaction_async(w3, ACCOUNTS["signer1"], **tx)
    assert receipt.status == 1


@pytest.mark.connect
def test_connect_transaction(connect_mantra):
    test_transaction(None, connect_mantra, diff=2)


def test_transaction(mantra, connect_mantra, diff=1):
    w3 = connect_mantra.w3
    gas_price = w3.eth.gas_price
    sender = ADDRS["community"]
    receiver = ADDRS["signer1"]

    # send transaction
    txhash_1 = send_transaction(
        w3,
        {"to": receiver, "value": 10000, "gasPrice": gas_price},
    )["transactionHash"]
    tx1 = w3.eth.get_transaction(txhash_1)
    assert tx1["transactionIndex"] == 0

    initial_block_number = w3.eth.get_block_number()

    # tx already in mempool
    with pytest.raises(web3.exceptions.Web3RPCError) as exc:
        send_transaction(
            w3,
            {
                "to": receiver,
                "value": 10000,
                "gasPrice": gas_price,
                "nonce": w3.eth.get_transaction_count(sender) - 1,
            },
        )
    assert "tx already in mempool" in str(exc)

    # invalid sequence
    with pytest.raises(web3.exceptions.Web3RPCError) as exc:
        send_transaction(
            w3,
            {
                "to": receiver,
                "value": 10000,
                "gasPrice": w3.eth.gas_price,
                "nonce": w3.eth.get_transaction_count(sender) + 1,
            },
        )
    assert "invalid sequence" in str(exc)

    # out of gas
    with pytest.raises(web3.exceptions.Web3RPCError) as exc:
        send_transaction(
            w3,
            {
                "to": receiver,
                "value": 10000,
                "gasPrice": w3.eth.gas_price,
                "gas": 1,
            },
        )["transactionHash"]
    assert "intrinsic gas too low" in str(exc)

    # insufficient fee
    with pytest.raises(web3.exceptions.Web3RPCError) as exc:
        send_transaction(
            w3,
            {
                "to": receiver,
                "value": 10000,
                "gasPrice": 1,
            },
        )["transactionHash"]
    assert "insufficient fee" in str(exc)

    # check all failed transactions are not included in blockchain
    assert w3.eth.get_block_number() - initial_block_number <= diff

    # Deploy multiple contracts
    contracts = {
        "test_revert_1": RevertTestContract(
            "TestRevert",
            KEYS["validator"],
        ),
        "test_revert_2": RevertTestContract(
            "TestRevert",
            KEYS["community"],
        ),
        "greeter_1": Greeter(
            "Greeter",
            KEYS["signer1"],
        ),
        "greeter_2": Greeter(
            "Greeter",
            KEYS["signer2"],
        ),
    }

    w3_wait_for_new_blocks(w3, 1)
    with ThreadPoolExecutor(4) as executor:
        future_to_contract = {
            executor.submit(contract.deploy, w3): name
            for name, contract in contracts.items()
        }

        assert_receipt_transaction_and_block(w3, future_to_contract)

    # Do Multiple contract calls
    w3_wait_for_new_blocks(w3, 1)
    with ThreadPoolExecutor(4) as executor:
        futures = []
        futures.append(
            executor.submit(contracts["test_revert_1"].transfer, 5 * (10**18) - 1)
        )
        futures.append(
            executor.submit(contracts["test_revert_2"].transfer, 5 * (10**18))
        )
        futures.append(executor.submit(contracts["greeter_1"].transfer, "hello"))
        futures.append(executor.submit(contracts["greeter_2"].transfer, "world"))

        assert_receipt_transaction_and_block(w3, futures)

        # revert transaction for 1st, normal transaction for others
        statuses = [0, 1, 1, 1]
        for i, future in enumerate(futures):
            assert future.result()["status"] == statuses[i]


def assert_receipt_transaction_and_block(w3, futures):
    receipts = []
    for future in as_completed(futures):
        data = future.result()
        receipts.append(data)
    assert len(receipts) == 4

    block_number = w3.eth.get_block_number()
    tx_indexes = [0, 1, 2, 3]
    for receipt in receipts:
        assert receipt["blockNumber"] == block_number
        transaction_index = receipt["transactionIndex"]
        assert transaction_index in tx_indexes
        tx_indexes.remove(transaction_index)

    block = w3.eth.get_block(block_number)
    transactions = [
        w3.eth.get_transaction_by_block(block_number, receipt["transactionIndex"])
        for receipt in receipts
    ]
    assert len(transactions) == 4
    for i, transaction in enumerate(transactions):
        assert transaction["blockNumber"] == block_number
        assert transaction["transactionIndex"] == receipts[i]["transactionIndex"]
        assert transaction["hash"] == receipts[i]["transactionHash"]
        assert transaction["hash"] in block["transactions"]
        assert transaction["blockNumber"] == block["number"]


@pytest.mark.connect
def test_connect_exception(connect_mantra):
    test_exception(None, connect_mantra)


def test_exception(mantra, connect_mantra):
    w3 = connect_mantra.w3
    key = KEYS["community"]
    revert = RevertTestContract("TestRevert", private_key=key)
    revert.deploy(w3)
    contract = revert.contract
    with pytest.raises(web3.exceptions.ContractLogicError):
        send_transaction(
            w3,
            contract.functions.transfer(5 * (10**18) - 1).build_transaction(),
            key=key,
        )
    assert 0 == contract.caller.query()

    receipt = send_transaction(
        w3, contract.functions.transfer(5 * (10**18)).build_transaction(), key=key
    )
    assert receipt.status == 1, "should be successfully"
    assert 5 * (10**18) == contract.caller.query()


@pytest.mark.connect
async def test_connect_message_call(connect_mantra):
    test_message_call(None, connect_mantra, diff=10)


def test_message_call(mantra, connect_mantra, diff=5):
    "stress test the evm by doing message calls as much as possible"
    w3 = connect_mantra.w3
    key = KEYS["community"]
    msg = Contract("TestMessageCall", private_key=key)
    msg.deploy(w3)
    iterations = 13000
    addr = ADDRS["community"]
    tx = msg.contract.functions.test(iterations).build_transaction(
        {
            "from": addr,
            "nonce": w3.eth.get_transaction_count(addr),
        }
    )

    begin = time.time()
    tx["gas"] = w3.eth.estimate_gas(tx)
    elapsed = time.time() - begin
    print("elapsed:", elapsed)
    assert elapsed < diff  # should finish in reasonable time

    receipt = send_transaction(w3, tx, key=key)
    assert 22768266 == receipt.cumulativeGasUsed
    assert receipt.status == 1, "shouldn't fail"
    assert len(receipt.logs) == iterations


@pytest.mark.connect
def test_connect_log0(connect_mantra):
    test_log0(None, connect_mantra)


def test_log0(mantra, connect_mantra):
    """
    test compliance of empty topics behavior
    """
    w3 = connect_mantra.w3
    key = KEYS["community"]
    empty = Contract("TestERC20A", private_key=key)
    empty.deploy(w3)
    contract = empty.contract
    tx = contract.functions.test_log0().build_transaction({"from": ADDRS["community"]})
    receipt = send_transaction(w3, tx, key=key)
    assert len(receipt.logs) == 1
    log = receipt.logs[0]
    assert log.topics == []
    data = "0x68656c6c6f20776f726c64000000000000000000000000000000000000000000"
    assert log.data == HexBytes(data)


@pytest.mark.connect
def test_connect_contract(connect_mantra, tmp_path):
    test_contract(None, connect_mantra, tmp_path)


def test_contract(mantra, connect_mantra, tmp_path):
    "test Greeter contract"
    cli = connect_mantra.cosmos_cli(tmp_path)
    recover_community(cli, tmp_path)
    w3 = connect_mantra.w3
    name = "community"
    key = KEYS[name]
    greeter = Greeter("Greeter", private_key=key)
    greeter.deploy(w3)
    contract = greeter.contract
    assert "Hello" == contract.caller.greet()
    # change
    tx = contract.functions.setGreeting("world").build_transaction()
    receipt = send_transaction(w3, tx, key=key)
    assert receipt.status == 1
    assert_balance(cli, w3, name)


@pytest.mark.connect
def test_connect_batch_tx(connect_mantra, tmp_path):
    test_batch_tx(None, connect_mantra, tmp_path)


def test_batch_tx(mantra, connect_mantra, tmp_path):
    "send multiple eth txs in single cosmos tx should be disabled"
    w3 = connect_mantra.w3
    cli = connect_mantra.cosmos_cli(tmp_path)
    sender = ADDRS["community"]
    recipient = ADDRS["signer1"]
    nonce = w3.eth.get_transaction_count(sender)
    res = build_contract("TestERC20A")
    contract = w3.eth.contract(abi=res["abi"], bytecode=res["bytecode"])
    deploy_tx = contract.constructor().build_transaction(
        {"from": sender, "nonce": nonce}
    )
    contract = w3.eth.contract(address=contract_address(sender, nonce), abi=res["abi"])
    transfer_tx1 = contract.functions.transfer(recipient, 1000).build_transaction(
        {"from": sender, "nonce": nonce + 1, "gas": 200000}
    )
    transfer_tx2 = contract.functions.transfer(recipient, 1000).build_transaction(
        {"from": sender, "nonce": nonce + 2, "gas": 200000}
    )

    cosmos_tx, tx_hashes = build_batch_tx(
        w3, cli, [deploy_tx, transfer_tx1, transfer_tx2], key=KEYS["community"]
    )
    rsp = cli.broadcast_tx_json(cosmos_tx)
    assert rsp["code"] == 18
    assert f"got {len(tx_hashes)}" in rsp["raw_log"]


@pytest.mark.connect
def test_connect_refund_unused_gas_when_contract_tx_reverted(connect_mantra):
    test_refund_unused_gas_when_contract_tx_reverted(None, connect_mantra)


def test_refund_unused_gas_when_contract_tx_reverted(mantra, connect_mantra):
    """
    Call a smart contract method that reverts with very high gas limit

    Call tx receipt should be status 0 (fail)
    Fee is gasUsed * effectiveGasPrice
    """
    w3 = connect_mantra.w3
    key = KEYS["community"]
    sender = ADDRS["community"]
    revert = RevertTestContract("TestRevert", private_key=key)
    revert.deploy(w3)
    contract = revert.contract
    more_than_enough_gas = 1000000

    balance_bef = w3.eth.get_balance(sender)
    receipt = send_transaction(
        w3,
        contract.functions.transfer(5 * (10**18) - 1).build_transaction(
            {"gas": more_than_enough_gas}
        ),
        key=key,
    )
    balance_aft = w3.eth.get_balance(sender)

    assert receipt["status"] == 0, "should be a failed tx"
    assert receipt["gasUsed"] != more_than_enough_gas
    assert (
        balance_bef - balance_aft == receipt["gasUsed"] * receipt["effectiveGasPrice"]
    )


@pytest.mark.skip(reason="skipping batch tx test")
def test_failed_transfer_tx(mantra):
    """
    It's possible to include a failed transfer transaction in batch tx
    """
    w3 = mantra.w3
    cli = mantra.cosmos_cli()
    sender = ADDRS["community"]
    recipient = ADDRS["signer1"]
    nonce = w3.eth.get_transaction_count(sender)
    half_balance = w3.eth.get_balance(sender) // 3 + 1

    # build batch tx, the third tx will fail, but will be included in block
    # because of the batch tx.
    transfer1 = {"from": sender, "nonce": nonce, "to": recipient, "value": half_balance}
    transfer2 = {
        "from": sender,
        "nonce": nonce + 1,
        "to": recipient,
        "value": half_balance,
    }
    transfer3 = {
        "from": sender,
        "nonce": nonce + 2,
        "to": recipient,
        "value": half_balance,
    }
    cosmos_tx, tx_hashes = build_batch_tx(
        w3, cli, [transfer1, transfer2, transfer3], KEYS["community"]
    )
    rsp = cli.broadcast_tx_json(cosmos_tx)
    assert rsp["code"] == 0, rsp["raw_log"]

    receipts = [w3.eth.wait_for_transaction_receipt(h) for h in tx_hashes]
    assert receipts[0].status == receipts[1].status == 1
    assert receipts[2].status == 0

    # check traceTransaction
    rsps = [
        w3.provider.make_request("debug_traceTransaction", [h.hex()]) for h in tx_hashes
    ]
    for rsp, receipt in zip(rsps, receipts):
        if receipt.status == 1:
            result = rsp["result"]
            assert not result["failed"]
            assert receipt.gasUsed == result["gas"]
        else:
            assert rsp["result"] == {
                "failed": True,
                "gas": 0,
                # "gas": 21000, TODO: mmsqe
                "returnValue": "0x",
                "structLogs": [],
            }


@pytest.mark.connect
def test_connect_multisig(connect_mantra, tmp_path):
    test_multisig(None, connect_mantra, tmp_path)


def test_multisig(mantra, connect_mantra, tmp_path):
    cli = connect_mantra.cosmos_cli(tmp_path)
    do_multisig(cli, tmp_path, "signer1", "signer2", "multitest1")


@pytest.mark.connect
def test_connect_multisig_cosmos(connect_mantra, tmp_path):
    test_multisig_cosmos(None, connect_mantra, tmp_path)


def test_multisig_cosmos(mantra, connect_mantra, tmp_path):
    cli = connect_mantra.cosmos_cli(tmp_path)
    recover1 = "recover1"
    recover2 = "recover2"
    amt = 6000
    addr_recover1 = cli.create_account(
        recover1,
        coin_type=118,
        key_type="secp256k1",
    )["address"]
    addr_recover2 = cli.create_account(
        recover2,
        coin_type=118,
        key_type="secp256k1",
    )["address"]
    sender = cli.address("community")
    transfer_via_cosmos(cli, sender, addr_recover1, amt)
    transfer_via_cosmos(cli, sender, addr_recover2, amt)
    do_multisig(cli, tmp_path, recover1, recover2, "multitest2")


@pytest.mark.connect
def test_connect_textual(connect_mantra, tmp_path):
    test_textual(None, connect_mantra, tmp_path)


def test_textual(mantra, connect_mantra, tmp_path):
    cli = connect_mantra.cosmos_cli(tmp_path)
    rsp = cli.transfer(
        cli.address("community"),
        cli.address("signer2"),
        f"1{DEFAULT_DENOM}",
        sign_mode="textual",
    )
    assert rsp["code"] == 0, rsp["raw_log"]

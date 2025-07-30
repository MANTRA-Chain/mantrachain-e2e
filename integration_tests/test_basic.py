import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
import web3
from eth_bloom import BloomFilter
from eth_utils import abi, big_endian_to_int
from hexbytes import HexBytes

from .utils import (
    ADDRS,
    CONTRACTS,
    DEFAULT_DENOM,
    KEYS,
    Greeter,
    RevertTestContract,
    assert_balance,
    assert_transfer,
    build_batch_tx,
    contract_address,
    deploy_contract,
    recover_community,
    send_transaction,
    transfer_via_cosmos,
    w3_wait_for_new_blocks,
)


def test_simple(mantra):
    """
    check number of validators
    """
    cli = mantra.cosmos_cli()
    assert len(cli.validators()) == 3
    # check vesting account
    addr = cli.address("reserve")
    account = cli.account(addr)["account"]
    assert account["type"] == "/cosmos.vesting.v1beta1.DelayedVestingAccount"
    assert account["value"]["base_vesting_account"]["original_vesting"] == [
        {"denom": DEFAULT_DENOM, "amount": "100000000000"}
    ]


def test_transfer(mantra):
    """
    check simple transfer tx success
    """
    cli = mantra.cosmos_cli()
    addr_a = cli.address("community")
    addr_b = cli.address("reserve")
    assert_transfer(cli, addr_a, addr_b)


def test_send_transaction(mantra):
    w3 = mantra.w3
    txhash = w3.eth.send_transaction(
        {
            "from": ADDRS["validator"],
            "to": ADDRS["community"],
            "value": 1000,
        }
    )
    receipt = w3.eth.wait_for_transaction_receipt(txhash)
    assert receipt.status == 1
    assert receipt.gasUsed == 21000


@pytest.mark.connect
def test_connect_events(connect_mantra):
    test_events(None, connect_mantra)


def test_events(mantra, connect_mantra):
    w3 = connect_mantra.w3
    sender = "community"
    receiver = "signer1"
    erc20 = deploy_contract(
        w3,
        CONTRACTS["TestERC20A"],
        key=KEYS[sender],
        exp_gas_used=914023,
    )
    tx = erc20.functions.transfer(ADDRS[receiver], 10).build_transaction(
        {"from": ADDRS[sender]}
    )
    txreceipt = send_transaction(w3, tx, KEYS[sender])
    assert len(txreceipt.logs) == 1
    data = "0x000000000000000000000000000000000000000000000000000000000000000a"
    expect_log = {
        "address": erc20.address,
        "topics": [
            HexBytes(
                abi.event_signature_to_log_topic("Transfer(address,address,uint256)")
            ),
            HexBytes(b"\x00" * 12 + HexBytes(ADDRS[sender])),
            HexBytes(b"\x00" * 12 + HexBytes(ADDRS[receiver])),
        ],
        "data": HexBytes(data),
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


def test_minimal_gas_price(mantra):
    w3 = mantra.w3
    gas_price = w3.eth.gas_price
    tx = {
        "to": "0x0000000000000000000000000000000000000000",
        "value": 10000,
    }
    with pytest.raises(web3.exceptions.Web3RPCError):
        send_transaction(
            w3,
            {**tx, "gasPrice": 1},
            KEYS["community"],
        )
    receipt = send_transaction(
        w3,
        {**tx, "gasPrice": gas_price},
        KEYS["validator"],
    )
    assert receipt.status == 1


def test_transaction(mantra):
    w3 = mantra.w3
    gas_price = w3.eth.gas_price

    # send transaction
    txhash_1 = send_transaction(
        w3,
        {"to": ADDRS["community"], "value": 10000, "gasPrice": gas_price},
        KEYS["validator"],
    )["transactionHash"]
    tx1 = w3.eth.get_transaction(txhash_1)
    assert tx1["transactionIndex"] == 0

    initial_block_number = w3.eth.get_block_number()

    # tx already in mempool
    with pytest.raises(web3.exceptions.Web3RPCError) as exc:
        send_transaction(
            w3,
            {
                "to": ADDRS["community"],
                "value": 10000,
                "gasPrice": gas_price,
                "nonce": w3.eth.get_transaction_count(ADDRS["validator"]) - 1,
            },
            KEYS["validator"],
        )
    assert "tx already in mempool" in str(exc)

    # invalid sequence
    with pytest.raises(web3.exceptions.Web3RPCError) as exc:
        send_transaction(
            w3,
            {
                "to": ADDRS["community"],
                "value": 10000,
                "gasPrice": w3.eth.gas_price,
                "nonce": w3.eth.get_transaction_count(ADDRS["validator"]) + 1,
            },
            KEYS["validator"],
        )
    assert "invalid sequence" in str(exc)

    # out of gas
    with pytest.raises(web3.exceptions.Web3RPCError) as exc:
        send_transaction(
            w3,
            {
                "to": ADDRS["community"],
                "value": 10000,
                "gasPrice": w3.eth.gas_price,
                "gas": 1,
            },
            KEYS["validator"],
        )["transactionHash"]
    assert "out of gas" in str(exc)

    # insufficient fee
    with pytest.raises(web3.exceptions.Web3RPCError) as exc:
        send_transaction(
            w3,
            {
                "to": ADDRS["community"],
                "value": 10000,
                "gasPrice": 1,
            },
            KEYS["validator"],
        )["transactionHash"]
    assert "insufficient fee" in str(exc)

    # check all failed transactions are not included in blockchain
    assert w3.eth.get_block_number() == initial_block_number

    # Deploy multiple contracts
    contracts = {
        "test_revert_1": RevertTestContract(
            CONTRACTS["TestRevert"],
            KEYS["validator"],
        ),
        "test_revert_2": RevertTestContract(
            CONTRACTS["TestRevert"],
            KEYS["community"],
        ),
        "greeter_1": Greeter(
            CONTRACTS["Greeter"],
            KEYS["signer1"],
        ),
        "greeter_2": Greeter(
            CONTRACTS["Greeter"],
            KEYS["signer2"],
        ),
    }

    with ThreadPoolExecutor(4) as executor:
        future_to_contract = {
            executor.submit(contract.deploy, w3): name
            for name, contract in contracts.items()
        }

        assert_receipt_transaction_and_block(w3, future_to_contract)

    # Do Multiple contract calls
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

        # revert transaction
        assert futures[0].result()["status"] == 0
        # normal transaction
        assert futures[1].result()["status"] == 1
        # normal transaction
        assert futures[2].result()["status"] == 1
        # normal transaction
        assert futures[3].result()["status"] == 1


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


def test_exception(mantra):
    w3 = mantra.w3
    contract = deploy_contract(
        w3,
        CONTRACTS["TestRevert"],
    )
    with pytest.raises(web3.exceptions.ContractLogicError):
        send_transaction(
            w3, contract.functions.transfer(5 * (10**18) - 1).build_transaction()
        )
    assert 0 == contract.caller.query()

    receipt = send_transaction(
        w3, contract.functions.transfer(5 * (10**18)).build_transaction()
    )
    assert receipt.status == 1, "should be successfully"
    assert 5 * (10**18) == contract.caller.query()


def test_message_call(mantra):
    "stress test the evm by doing message calls as much as possible"
    w3 = mantra.w3
    contract = deploy_contract(
        w3,
        CONTRACTS["TestMessageCall"],
    )
    iterations = 13000
    addr = ADDRS["validator"]
    tx = contract.functions.test(iterations).build_transaction(
        {
            "from": addr,
            "nonce": w3.eth.get_transaction_count(addr),
        }
    )

    begin = time.time()
    tx["gas"] = w3.eth.estimate_gas(tx)
    elapsed = time.time() - begin
    print("elapsed:", elapsed)
    assert elapsed < 5  # should finish in reasonable time

    receipt = send_transaction(w3, tx)
    assert 22326250 == receipt.cumulativeGasUsed
    assert receipt.status == 1, "shouldn't fail"
    assert len(receipt.logs) == iterations


def test_log0(mantra):
    """
    test compliance of empty topics behavior
    """
    w3 = mantra.w3
    contract = deploy_contract(
        w3,
        CONTRACTS["TestERC20A"],
    )
    tx = contract.functions.test_log0().build_transaction({"from": ADDRS["validator"]})
    receipt = send_transaction(w3, tx, KEYS["validator"])
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
    contract = deploy_contract(w3, CONTRACTS["Greeter"], key=key)
    assert "Hello" == contract.caller.greet()
    # change
    tx = contract.functions.setGreeting("world").build_transaction()
    receipt = send_transaction(w3, tx, key=key)
    assert receipt.status == 1
    assert_balance(cli, w3, name)


def test_batch_tx(mantra):
    "send multiple eth txs in single cosmos tx should be disabled"
    w3 = mantra.w3
    cli = mantra.cosmos_cli()
    sender = ADDRS["validator"]
    recipient = ADDRS["community"]
    nonce = w3.eth.get_transaction_count(sender)
    info = json.loads(CONTRACTS["TestERC20A"].read_text())
    contract = w3.eth.contract(abi=info["abi"], bytecode=info["bytecode"])
    deploy_tx = contract.constructor().build_transaction(
        {"from": sender, "nonce": nonce}
    )
    contract = w3.eth.contract(address=contract_address(sender, nonce), abi=info["abi"])
    transfer_tx1 = contract.functions.transfer(recipient, 1000).build_transaction(
        {"from": sender, "nonce": nonce + 1, "gas": 200000}
    )
    transfer_tx2 = contract.functions.transfer(recipient, 1000).build_transaction(
        {"from": sender, "nonce": nonce + 2, "gas": 200000}
    )

    cosmos_tx, tx_hashes = build_batch_tx(
        w3, cli, [deploy_tx, transfer_tx1, transfer_tx2]
    )
    rsp = cli.broadcast_tx_json(cosmos_tx)
    assert rsp["code"] == 18
    assert f"got {len(tx_hashes)}" in rsp["raw_log"]


def test_refund_unused_gas_when_contract_tx_reverted(mantra):
    """
    Call a smart contract method that reverts with very high gas limit

    Call tx receipt should be status 0 (fail)
    Fee is gasUsed * effectiveGasPrice
    """
    w3 = mantra.w3
    contract = deploy_contract(w3, CONTRACTS["TestRevert"])
    more_than_enough_gas = 1000000

    balance_bef = w3.eth.get_balance(ADDRS["community"])
    receipt = send_transaction(
        w3,
        contract.functions.transfer(5 * (10**18) - 1).build_transaction(
            {"gas": more_than_enough_gas}
        ),
        key=KEYS["community"],
    )
    balance_aft = w3.eth.get_balance(ADDRS["community"])

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
    recipient = ADDRS["validator"]
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


def test_multisig(mantra, tmp_path):
    cli = mantra.cosmos_cli()
    cli.make_multisig("multitest1", "signer1", "signer2")
    multi_addr = cli.address("multitest1")
    signer1 = cli.address("signer1")
    amt = 4000
    cli.transfer(signer1, multi_addr, f"{amt}{DEFAULT_DENOM}")
    acc = cli.account(multi_addr)
    res = cli.account_by_num(acc["account"]["value"]["account_number"])
    assert res["account_address"] == multi_addr

    m_txt = tmp_path / "m.txt"
    p1_txt = tmp_path / "p1.txt"
    p2_txt = tmp_path / "p2.txt"
    tx_txt = tmp_path / "tx.txt"
    amt = 1
    signer2 = cli.address("signer2")
    multi_tx = cli.transfer(
        multi_addr,
        signer2,
        f"{amt}{DEFAULT_DENOM}",
        generate_only=True,
    )
    json.dump(multi_tx, m_txt.open("w"))
    signature1 = cli.sign_multisig_tx(m_txt, multi_addr, "signer1")
    json.dump(signature1, p1_txt.open("w"))
    signature2 = cli.sign_multisig_tx(m_txt, multi_addr, "signer2")
    json.dump(signature2, p2_txt.open("w"))
    final_multi_tx = cli.combine_multisig_tx(
        m_txt,
        "multitest1",
        p1_txt,
        p2_txt,
    )
    json.dump(final_multi_tx, tx_txt.open("w"))
    rsp = cli.broadcast_tx(tx_txt)
    assert rsp["code"] == 0, rsp["raw_log"]
    assert cli.account(multi_addr)["account"]["value"]["address"] == multi_addr


def test_multisig_cosmos(mantra, tmp_path):
    cli = mantra.cosmos_cli()
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
    cli.make_multisig("multitest2", recover1, recover2)
    multi_addr = cli.address("multitest2")
    signer1 = cli.address(recover1)
    amt = 4000
    rsp = cli.transfer(signer1, multi_addr, f"{amt}{DEFAULT_DENOM}")
    assert rsp["code"] == 0, rsp["raw_log"]
    acc = cli.account(multi_addr)
    res = cli.account_by_num(acc["account"]["value"]["account_number"])
    assert res["account_address"] == multi_addr

    m_txt = tmp_path / "m.txt"
    p1_txt = tmp_path / "p1.txt"
    p2_txt = tmp_path / "p2.txt"
    tx_txt = tmp_path / "tx.txt"
    amt = 1
    signer2 = cli.address(recover2)
    multi_tx = cli.transfer(
        multi_addr,
        signer2,
        f"{amt}{DEFAULT_DENOM}",
        generate_only=True,
    )
    json.dump(multi_tx, m_txt.open("w"))
    signature1 = cli.sign_multisig_tx(m_txt, multi_addr, recover1)
    json.dump(signature1, p1_txt.open("w"))
    signature2 = cli.sign_multisig_tx(m_txt, multi_addr, recover2)
    json.dump(signature2, p2_txt.open("w"))
    final_multi_tx = cli.combine_multisig_tx(
        m_txt,
        "multitest2",
        p1_txt,
        p2_txt,
    )
    json.dump(final_multi_tx, tx_txt.open("w"))
    rsp = cli.broadcast_tx(tx_txt)
    assert rsp["code"] == 0, rsp["raw_log"]
    assert cli.account(multi_addr)["account"]["value"]["address"] == multi_addr


def test_textual(mantra):
    cli = mantra.cosmos_cli()
    rsp = cli.transfer(
        cli.address("validator"),
        cli.address("signer2"),
        f"1{DEFAULT_DENOM}",
        sign_mode="textual",
    )
    assert rsp["code"] == 0, rsp["raw_log"]


@pytest.mark.skip(reason="skipping opBlockhash test")
def test_op_blk_hash(mantra):
    w3 = mantra.w3
    contract = deploy_contract(w3, CONTRACTS["TestBlockTxProperties"])
    height = w3.eth.get_block_number()
    w3_wait_for_new_blocks(w3, 1)
    res = contract.caller.getBlockHash(height).hex()
    blk = w3.eth.get_block(height)
    assert res == blk.hash.hex(), res

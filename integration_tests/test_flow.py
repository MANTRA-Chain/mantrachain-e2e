import os
from itertools import takewhile

import pytest
from eth_account import Account

from .network import ConnectMantra, Mantra
from .utils import (
    ADDRS,
    DEFAULT_DENOM,
    DEFAULT_FEE,
    WEI_PER_UOM,
    assert_balance,
    eth_to_bech32,
    find_log_event_attrs,
    send_transaction,
)


def get_fee(events):
    attrs = find_log_event_attrs(events, "tx", lambda attrs: "fee" in attrs)
    return int("".join(takewhile(lambda s: s.isdigit() or s == ".", attrs["fee"])))


def fund_recover(m: Mantra, tmp_path):
    """
    transfer fund from community to recover cosmos addr
    """
    community = "community"
    addr_community = eth_to_bech32(ADDRS[community])
    assert addr_community == "mantra1x7x9pkfxf33l87ftspk5aetwnkr0lvlvdy9gff"
    cli = m.cosmos_cli()
    w3 = m.w3
    assert (
        cli.create_account(
            community,
            mnemonic=os.getenv("COMMUNITY_MNEMONIC"),
            home=tmp_path,
        )["address"]
        == addr_community
    )
    balance_community = assert_balance(cli, w3, addr_community)
    addr_recover = "mantra1h5tsd8wjefus259xmff367ltg0rpf54a9ktpza"
    balance_recover = assert_balance(cli, w3, addr_recover)
    amt = 4000
    if balance_recover >= amt:
        return
    chain_id = cli.chain_id
    tx = cli.transfer(
        addr_community,
        addr_recover,
        f"{amt}{DEFAULT_DENOM}",
        generate_only=True,
        chain_id=chain_id,
    )
    tx_json = cli.sign_tx_json(
        tx, addr_community, home=tmp_path, node=m.node_rpc(0), chain_id=chain_id
    )
    rsp = cli.broadcast_tx_json(tx_json, home=tmp_path)
    assert rsp["code"] == 0, rsp["raw_log"]
    fee = get_fee(rsp["events"])
    assert fee == DEFAULT_FEE
    assert assert_balance(cli, w3, addr_community) == balance_community - amt - fee
    assert assert_balance(cli, w3, addr_recover) == balance_recover + amt


def run_flow(m: ConnectMantra, tmp_path):
    community = "community"
    recover = "recover"
    amt = 4000
    addr_recover = "mantra1h5tsd8wjefus259xmff367ltg0rpf54a9ktpza"

    # recover cosmos addr outside from node
    cli = m.cosmos_cli(tmp_path)
    assert (
        cli.create_account(
            recover,
            mnemonic=os.getenv("RECOVER_MNEMONIC"),
            coin_type=118,
            key_type="secp256k1",
            home=tmp_path,
        )["address"]
        == addr_recover
    )
    w3 = m.w3
    assert assert_balance(cli, w3, recover) >= amt

    # fund test1 from all recover's balance via cosmos tx
    acc_test1 = Account.from_mnemonic(os.getenv("TESTER1_MNEMONIC"))
    addr_test1 = eth_to_bech32(acc_test1.address)
    amt2 = amt - DEFAULT_FEE
    chain_id = cli.chain_id
    tx = cli.transfer(
        addr_recover,
        addr_test1,
        f"{amt2}{DEFAULT_DENOM}",
        generate_only=True,
        chain_id=chain_id,
    )
    tx_json = cli.sign_tx_json(
        tx, addr_recover, home=tmp_path, node=m.rpc, chain_id=chain_id
    )
    rsp = cli.broadcast_tx_json(tx_json, home=tmp_path)
    assert rsp["code"] == 0, rsp["raw_log"]
    fee = get_fee(rsp["events"])
    assert fee == DEFAULT_FEE
    assert assert_balance(cli, w3, addr_test1) == amt2
    assert assert_balance(cli, w3, addr_recover) == amt2 - fee

    # send 1 wei from test1 to test2 for tolerance check
    acc_test2 = Account.from_mnemonic(os.getenv("TESTER2_MNEMONIC"))
    addr_test2 = eth_to_bech32(acc_test2.address)
    value = 1
    gas_price = 11250000000
    gas = 21000
    evm_tx = {
        "to": acc_test2.address,
        "value": value,
        "gas": gas,
        "gasPrice": gas_price,
        "nonce": w3.eth.get_transaction_count(acc_test1.address),
    }
    receipt = send_transaction(w3, evm_tx, acc_test1.key)
    assert receipt.status == 1
    evm_fee = receipt.gasUsed * receipt.effectiveGasPrice
    assert w3.eth.get_balance(acc_test2.address) == value
    assert assert_balance(cli, w3, addr_test2) == value // WEI_PER_UOM
    amt2 = (amt2 * WEI_PER_UOM - evm_fee) // WEI_PER_UOM
    assert assert_balance(cli, w3, addr_test1) == amt2

    # send 10^12 wei from test1 to test2 for tolerance check
    value = 10**12
    evm_tx["value"] = value
    evm_tx["nonce"] = w3.eth.get_transaction_count(acc_test1.address)
    receipt = send_transaction(w3, evm_tx, acc_test1.key)
    assert receipt.status == 1
    evm_fee = receipt.gasUsed * receipt.effectiveGasPrice
    assert w3.eth.get_balance(acc_test2.address) == value + 1
    assert assert_balance(cli, w3, addr_test2) == value // WEI_PER_UOM
    amt2 = (amt2 * WEI_PER_UOM - evm_fee) // WEI_PER_UOM
    assert assert_balance(cli, w3, addr_test1) == amt2

    # recycle test1's balance back to community
    balance_community_evm = w3.eth.get_balance(ADDRS[community])
    value = w3.eth.get_balance(acc_test1.address) - gas * gas_price
    evm_tx["to"] = ADDRS[community]
    evm_tx["value"] = value
    evm_tx["nonce"] = w3.eth.get_transaction_count(acc_test1.address)
    receipt = send_transaction(w3, evm_tx, acc_test1.key)
    assert receipt.status == 1
    assert w3.eth.get_balance(acc_test1.address) == 0
    assert w3.eth.get_balance(ADDRS[community]) == balance_community_evm + value
    assert assert_balance(cli, w3, eth_to_bech32(ADDRS[community])) > 0


@pytest.mark.connect
def test_connect_connect_flow(connect_mantra, tmp_path):
    run_flow(connect_mantra, tmp_path)


def test_flow(mantra, connect_mantra, tmp_path):
    fund_recover(mantra, tmp_path)
    run_flow(connect_mantra, tmp_path)

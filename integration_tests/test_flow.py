import os

import pytest

from .network import ConnectMantra
from .utils import (
    ADDRS,
    DEFAULT_FEE,
    WEI_PER_DENOM,
    assert_balance,
    derive_new_account,
    eth_to_bech32,
    get_balance,
    recover_community,
    send_transaction,
    transfer_via_cosmos,
)


@pytest.mark.connect
def test_connect_flow(connect_mantra, tmp_path):
    test_flow(None, connect_mantra, tmp_path)


def test_flow(mantra, connect_mantra: ConnectMantra, tmp_path):
    community = "community"
    recover = "recover"
    amt = 4_000_000_000_000_000 // WEI_PER_DENOM
    # recover cosmos addr outside from node
    cli = connect_mantra.cosmos_cli(tmp_path)
    w3 = connect_mantra.w3
    addr_recover = cli.create_account(
        recover,
        mnemonic=os.getenv("RECOVER_MNEMONIC"),
        coin_type=118,
        key_type="secp256k1",
        home=tmp_path,
    )["address"]
    addr_community = recover_community(cli, tmp_path)
    balance_recover = get_balance(cli, recover)
    balance_community = get_balance(cli, community)
    if balance_recover < amt and balance_community >= amt:
        # transfer fund from community to recover cosmos addr
        fee = transfer_via_cosmos(cli, addr_community, addr_recover, amt)
        assert assert_balance(cli, w3, community) == balance_community - amt - fee
        assert assert_balance(cli, w3, recover) == balance_recover + amt

    # fund test1 from recover via cosmos tx
    acc_test1 = derive_new_account(n=101)
    addr_test1 = eth_to_bech32(acc_test1.address)
    balance_recover = get_balance(cli, recover)
    balance1 = get_balance(cli, addr_test1)
    amt = amt - DEFAULT_FEE
    fee = transfer_via_cosmos(cli, addr_recover, addr_test1, amt)
    assert assert_balance(cli, w3, recover) == balance_recover - amt - fee
    assert assert_balance(cli, w3, addr_test1) == balance1 + amt
    balance1 = get_balance(cli, addr_test1)
    balance1_evm = w3.eth.get_balance(acc_test1.address)

    # send [1, 10**12] wei from test1 to test2 for tolerance check
    acc_test2 = derive_new_account(n=102)
    addr_test2 = eth_to_bech32(acc_test2.address)
    gas_price = 11250000000
    gas = 21000
    balance2_evm = w3.eth.get_balance(acc_test2.address)
    for value in [1, 10**12]:
        tx_evm = {
            "to": acc_test2.address,
            "value": value,
            "gas": gas,
            "gasPrice": gas_price,
            "nonce": w3.eth.get_transaction_count(acc_test1.address),
        }
        receipt = send_transaction(w3, tx_evm, acc_test1.key)
        assert receipt.status == 1
        balance2_evm += value
        assert assert_balance(cli, w3, addr_test2, True) == balance2_evm
        fee_evm = receipt.gasUsed * receipt.effectiveGasPrice
        balance1_evm -= value + fee_evm
        balance1 = balance1_evm // WEI_PER_DENOM
        assert assert_balance(cli, w3, addr_test1) == balance1
        assert assert_balance(cli, w3, addr_test1, True) == balance1_evm

    # recycle test1's balance back to community
    balance_community_evm = w3.eth.get_balance(ADDRS[community])
    value = w3.eth.get_balance(acc_test1.address) - gas * gas_price
    tx_evm = {
        "to": ADDRS[community],
        "value": value,
        "gas": gas,
        "gasPrice": gas_price,
        "nonce": w3.eth.get_transaction_count(acc_test1.address),
    }
    receipt = send_transaction(w3, tx_evm, acc_test1.key)
    assert receipt.status == 1
    balance_community_evm += value
    assert w3.eth.get_balance(acc_test1.address) == 0
    assert assert_balance(cli, w3, community, True) == balance_community_evm

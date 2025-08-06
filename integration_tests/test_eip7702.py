from .utils import send_transaction, wait_for_fn


def test_eoa(mantra):
    w3 = mantra.w3
    # fund new acct
    acct = w3.eth.account.create()
    value = 10**18
    tx = {
        "to": acct.address,
        "value": value,
    }
    tx_hash = send_transaction(w3, tx)
    # send 7702 tx
    chain_id = w3.eth.chain_id
    nonce = w3.eth.get_transaction_count(acct.address)
    new_dst_balance = 0

    def check_balance_change():
        nonlocal new_dst_balance
        new_dst_balance = w3.eth.get_balance(acct.address)
        return new_dst_balance != 0

    wait_for_fn("balance change", check_balance_change)
    assert w3.eth.get_balance(acct.address) == value

    authz = acct.sign_authorization(
        {
            "address": "0xdeadbeef00000000000000000000000000000000",
            "chainId": chain_id,
            "nonce": nonce + 1,
        }
    )
    tx = {
        "chainId": chain_id,
        "nonce": nonce,
        "gas": 200_000,
        "maxFeePerGas": 10**11,
        "maxPriorityFeePerGas": 10**11,
        "to": acct.address,
        "value": 0,
        "accessList": [],
        "authorizationList": [authz],
        "data": "0x",
    }
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    res = w3.eth.wait_for_transaction_receipt(tx_hash)
    assert res.status == 1
    # TODO: db sync fix release https://github.com/ethereum/go-ethereum/pull/31703
    code = w3.eth.get_code(acct.address, block_identifier=res["blockNumber"])
    assert code.hex().startswith("ef0100deadbeef"), "Code was not set!"

    # clear code
    clear_tx = dict(tx)  # copy tx and replace relevant fields
    clear_tx["nonce"] = nonce + 2
    clear_tx["authorizationList"] = [
        acct.sign_authorization(
            {
                "chainId": chain_id,
                "address": f"0x{'00' * 20}",
                "nonce": nonce + 3,
            }
        )
    ]
    signed_reset = acct.sign_transaction(clear_tx)
    clear_tx_hash = w3.eth.send_raw_transaction(signed_reset.raw_transaction)
    res = w3.eth.wait_for_transaction_receipt(clear_tx_hash)
    assert res.status == 1
    reset_code = w3.eth.get_code(acct.address)
    assert reset_code.hex().startswith(""), "Code was not clear!"

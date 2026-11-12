import pytest
import web3
from eth_account import Account
from eth_contract.contract import Contract
from eth_contract.erc20 import ERC20
from eth_contract.utils import get_initcode
from eth_contract.weth import WETH, WETH9_ARTIFACT

from .utils import (
    ACCOUNTS,
    DEFAULT_DENOM,
    WEI_PER_DENOM,
    WOM,
    assert_transfer,
    bech32_to_eth,
    build_contract,
    eth_to_bech32,
    fund_acc,
    module_address,
    send_transaction,
    submit_gov_proposal,
    wait_for_eth_tx_result,
)

pytestmark = pytest.mark.slow

GOV = module_address("gov")
# code-less delegation target, so calling a delegated account runs nothing
DELEGATE = "0xdeadbeef00000000000000000000000000000000"
DESIGNATOR = bytes.fromhex("ef0100" + DELEGATE[2:])


def require_sanction(cli):
    if not cli.has_module("wasm"):
        pytest.skip("sanction module not enabled")


def propose(mantra, tmp_path, kind, **fields):
    msg = {"@type": f"/mantrachain.sanction.v1.Msg{kind}", **fields}
    # the default 200k gas falls just short of the proposal's deposit write
    submit_gov_proposal(mantra, tmp_path, [msg], gas=300_000)


def test_blacklist(mantra, tmp_path):
    cli = mantra.cosmos_cli()
    require_sanction(cli)
    community = cli.address("community")
    user = cli.create_account("user")["address"]
    amt = 9_000_000_000_000_000 // WEI_PER_DENOM
    assert_transfer(cli, community, user, amt=amt)
    # upper-case bech32 used to be stored as typed and never matched
    fields = {"signer": GOV, "addresses": [user.upper()], "reason": "e2e"}
    propose(mantra, tmp_path, "SanctionAddresses", **fields)
    assert user in cli.query_blacklist()

    err = f"{bech32_to_eth(user)} is blacklisted"
    with pytest.raises(web3.exceptions.Web3RPCError, match=err):
        mantra.w3.eth.send_transaction(
            {
                "from": bech32_to_eth(user),
                "to": bech32_to_eth(community),
                "value": 1000,
            }
        )
    rsp = cli.transfer(user, community, f"1{DEFAULT_DENOM}")
    assert rsp["code"] != 0 and "is blacklisted" in rsp["raw_log"], rsp
    # receiving still works
    assert_transfer(cli, community, user)

    propose(mantra, tmp_path, "UnsanctionAddresses", **fields)
    assert_transfer(cli, user, community)


def test_single_msg_exec_per_tx(mantra):
    cli = mantra.cosmos_cli()
    granter = cli.address("signer1")
    grantee = cli.address("signer2")
    receiver = cli.address("community")

    tx = cli.transfer(granter, receiver, f"1{DEFAULT_DENOM}", generate_only=True)
    send_msg = tx["body"]["messages"][0]
    exec_msg = {
        "@type": "/cosmos.authz.v1beta1.MsgExec",
        "grantee": grantee,
        "msgs": [send_msg],
    }
    tx["body"]["messages"] = [exec_msg, exec_msg]

    signed = cli.sign_tx_json(tx, "signer2")
    rsp = cli.broadcast_tx_json(signed)
    assert rsp.get("code") != 0, rsp
    assert "only a single MsgExec" in rsp.get("raw_log", ""), rsp


def funded_account(w3):
    acct = Account.create()
    fund_acc(w3, acct)
    return acct


def deploy(w3, artifact):
    return send_transaction(w3, {"data": get_initcode(artifact)})["contractAddress"]


def delegate(w3, authority, target, data="0x"):
    "Delegate `authority` to `target` and call it, with community paying the gas."
    auth = authority.sign_authorization(
        {
            "chainId": w3.eth.chain_id,
            "address": target,
            "nonce": w3.eth.get_transaction_count(authority.address),
        }
    )
    tx = {
        "to": authority.address,
        "value": 0,
        "data": data,
        "gas": 200_000,
        "authorizationList": [auth],
    }
    return send_transaction(w3, tx)


@pytest.fixture(scope="module")
def sanction(mantra, tmp_path_factory):
    "Sanction an address in one tx, as a sanctioner appointed for the module."
    cli = mantra.cosmos_cli()
    require_sanction(cli)
    tmp_path = tmp_path_factory.mktemp("sanctioner")
    sanctioner = {"address": cli.address("signer1"), "role": "SANCTIONER_ROLE_FULL"}
    propose(
        mantra, tmp_path, "UpdateSanctioners", authority=GOV, sanctioners=[sanctioner]
    )

    def sanction(address):
        rsp = cli.sanction_addresses([eth_to_bech32(address)], "e2e", from_="signer1")
        assert rsp["code"] == 0, rsp["raw_log"]

    yield sanction
    propose(mantra, tmp_path, "UpdateSanctioners", authority=GOV, sanctioners=[])


def test_eip7702_delegation_cleared(mantra, sanction):
    w3 = mantra.w3
    acct = funded_account(w3)
    assert delegate(w3, acct, DELEGATE)["status"] == 1
    assert w3.eth.get_code(acct.address) == DESIGNATOR
    balance = w3.eth.get_balance(acct.address)

    # a 32-byte address only ends in the account's 20 bytes
    sanction(bytes(12) + bytes.fromhex(acct.address[2:]))
    assert w3.eth.get_code(acct.address) == DESIGNATOR

    sanction(acct.address)
    assert not w3.eth.get_code(acct.address)
    assert w3.eth.get_balance(acct.address) == balance


def test_eip7702_sweep(mantra, sanction):
    "A sponsored delegation to Sweeper drains an account unless it is sanctioned."
    w3 = mantra.w3
    artifact = build_contract("Sweeper")
    sweeper = deploy(w3, artifact)
    attacker = Account.create().address
    sweep = Contract(artifact["abi"]).fns.sweep(attacker).data

    victim = funded_account(w3)
    stolen = w3.eth.get_balance(victim.address)
    assert delegate(w3, victim, sweeper, sweep)["status"] == 1
    assert w3.eth.get_balance(victim.address) == 0
    assert w3.eth.get_balance(attacker) == stolen

    victim = funded_account(w3)
    held = w3.eth.get_balance(victim.address)
    sanction(victim.address)
    err = f"authorization signer {victim.address} is blacklisted"
    with pytest.raises(web3.exceptions.Web3RPCError, match=err):
        delegate(w3, victim, sweeper, sweep)
    assert w3.eth.get_balance(victim.address) == held


def test_allowance_from_blacklisted(mantra, sanction):
    "An allowance granted before the sanction can't move the owner's funds."
    w3 = mantra.w3
    owner = funded_account(w3)
    spender = ACCOUNTS["signer1"]
    amt = 10**18 // WEI_PER_DENOM
    # WOM is the bank-backed precompile of the EVM denom
    approve = {"to": WOM, "data": ERC20.fns.approve(spender.address, 2 * amt).data}
    assert send_transaction(w3, approve, key=owner.key)["status"] == 1

    def transfer_from():
        data = ERC20.fns.transferFrom(owner.address, spender.address, amt).data
        tx = {"to": WOM, "data": data, "gas": 200_000}
        return send_transaction(w3, tx, key=spender.key)["status"]

    before = w3.eth.get_balance(owner.address)
    assert transfer_from() == 1
    after = w3.eth.get_balance(owner.address)
    assert after < before

    sanction(owner.address)
    assert transfer_from() == 0
    assert w3.eth.get_balance(owner.address) == after


async def test_contract_funds_blacklisted(mantra, sanction):
    "A sanctioned contract can't send the funds it holds, whoever calls it."
    w3 = mantra.w3
    cli = mantra.cosmos_cli()
    weth = deploy(w3, WETH9_ARTIFACT)
    owner = funded_account(w3)
    deposit = {"to": weth, "data": WETH.fns.deposit().data, "value": 10**18}
    assert send_transaction(w3, deposit, key=owner.key)["status"] == 1
    withdraw = {"to": weth, "data": WETH.fns.withdraw(10**17).data, "gas": 200_000}
    assert send_transaction(w3, withdraw, key=owner.key)["status"] == 1

    sanction(weth)
    held = w3.eth.get_balance(weth)
    # the outflow commits as a bank send, which the send restriction rejects
    height = cli.block_height()
    txhash = send_transaction(w3, withdraw, key=owner.key, check=False)
    res = await wait_for_eth_tx_result(cli, mantra.async_w3, txhash, height)
    assert (res["codespace"], res["code"]) == ("sanction", 500), res
    assert w3.eth.get_balance(weth) == held

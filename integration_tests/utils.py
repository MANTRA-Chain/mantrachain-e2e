import configparser
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import takewhile
from pathlib import Path
from urllib.parse import urlparse

import bech32
import eth_utils
import rlp
from dateutil.parser import isoparse
from dotenv import load_dotenv
from eth_account import Account
from eth_utils import to_checksum_address
from hexbytes import HexBytes
from web3._utils.transactions import fill_nonce, fill_transaction_defaults

load_dotenv(Path(__file__).parent.parent / "scripts/.env")
Account.enable_unaudited_hdwallet_features()
ACCOUNTS = {
    "validator": Account.from_mnemonic(os.getenv("VALIDATOR1_MNEMONIC")),
    "validator2": Account.from_mnemonic(os.getenv("VALIDATOR2_MNEMONIC")),
    "validator3": Account.from_mnemonic(os.getenv("VALIDATOR3_MNEMONIC")),
    "community": Account.from_mnemonic(os.getenv("COMMUNITY_MNEMONIC")),
    "signer1": Account.from_mnemonic(os.getenv("SIGNER1_MNEMONIC")),
    "signer2": Account.from_mnemonic(os.getenv("SIGNER2_MNEMONIC")),
}
KEYS = {name: account.key for name, account in ACCOUNTS.items()}
ADDRS = {name: account.address for name, account in ACCOUNTS.items()}

DEFAULT_DENOM = "uom"
CHAIN_ID = "mantra-canary-net-1"
# the default initial base fee used by integration tests
DEFAULT_GAS_AMT = 0.01
DEFAULT_GAS_PRICE = f"{DEFAULT_GAS_AMT}{DEFAULT_DENOM}"
DEFAULT_GAS = 200000
DEFAULT_FEE = int(DEFAULT_GAS_AMT * DEFAULT_GAS)
WEI_PER_ETH = 10**18  # 10^18 wei == 1 ether
UOM_PER_OM = 10**6  # 10^6 uom == 1 om
WEI_PER_UOM = 10**12  # 10^12 wei == 1 uom
ADDRESS_PREFIX = "mantra"

TEST_CONTRACTS = {
    "TestERC20A": "TestERC20A.sol",
    "TestRevert": "TestRevert.sol",
    "Greeter": "Greeter.sol",
    "TestMessageCall": "TestMessageCall.sol",
    "SelfDestruct": "SelfDestruct.sol",
    "TestBlockTxProperties": "TestBlockTxProperties.sol",
    "Random": "Random.sol",
    "TestExploitContract": "TestExploitContract.sol",
    "BurnGas": "BurnGas.sol",
}


def contract_path(name, filename):
    return (
        Path(__file__).parent
        / "contracts/artifacts/contracts"
        / filename
        / (name + ".json")
    )


CONTRACTS = {
    **{
        name: contract_path(name, filename) for name, filename in TEST_CONTRACTS.items()
    },
}


class Contract:
    def __init__(self, contract_path, private_key=KEYS["validator"], chain_id=5887):
        self.chain_id = chain_id
        self.account = Account.from_key(private_key)
        self.address = self.account.address
        self.private_key = private_key
        with open(contract_path) as f:
            json_data = f.read()
            contract_json = json.loads(json_data)
        self.bytecode = contract_json["bytecode"]
        self.abi = contract_json["abi"]
        self.contract = None
        self.w3 = None

    def deploy(self, w3):
        "Deploy contract on `w3` and return the receipt."
        if self.contract is None:
            self.w3 = w3
            contract = self.w3.eth.contract(abi=self.abi, bytecode=self.bytecode)
            transaction = contract.constructor().build_transaction(
                {"chainId": self.chain_id, "from": self.address}
            )
            receipt = send_transaction(self.w3, transaction, self.private_key)
            self.contract = self.w3.eth.contract(
                address=receipt.contractAddress, abi=self.abi
            )
            return receipt
        else:
            return receipt


class Greeter(Contract):
    "Greeter contract."

    def transfer(self, string):
        "Call contract on `w3` and return the receipt."
        transaction = self.contract.functions.setGreeting(string).build_transaction(
            {
                "chainId": self.chain_id,
                "from": self.address,
            }
        )
        receipt = send_transaction(self.w3, transaction, self.private_key)
        assert string == self.contract.functions.greet().call()
        return receipt


class RevertTestContract(Contract):
    "RevertTestContract contract."

    def transfer(self, value):
        "Call contract on `w3` and return the receipt."
        transaction = self.contract.functions.transfer(value).build_transaction(
            {
                "chainId": self.chain_id,
                "from": self.address,
                "gas": 100000,  # skip estimateGas error
            }
        )
        receipt = send_transaction(self.w3, transaction, self.private_key)
        return receipt


def wait_for_fn(name, fn, *, timeout=240, interval=1):
    for i in range(int(timeout / interval)):
        result = fn()
        if result:
            return result
        time.sleep(interval)
    else:
        raise TimeoutError(f"wait for {name} timeout")


def wait_for_block_time(cli, t):
    print("wait for block time", t)
    while True:
        now = isoparse(get_sync_info(cli.status())["latest_block_time"])
        print("block time now:", now)
        if now >= t:
            break
        time.sleep(0.5)


def w3_wait_for_block(w3, height, timeout=240):
    for _ in range(timeout * 2):
        try:
            current_height = w3.eth.block_number
        except Exception as e:
            print(f"get json-rpc block number failed: {e}", file=sys.stderr)
        else:
            if current_height >= height:
                break
            print("current block height", current_height)
        time.sleep(0.5)
    else:
        raise TimeoutError(f"wait for block {height} timeout")


def get_sync_info(s):
    return s.get("SyncInfo") or s.get("sync_info")


def wait_for_new_blocks(cli, n, sleep=0.5, timeout=240):
    cur_height = begin_height = int(get_sync_info(cli.status())["latest_block_height"])
    start_time = time.time()
    while cur_height - begin_height < n:
        time.sleep(sleep)
        cur_height = int(get_sync_info(cli.status())["latest_block_height"])
        if time.time() - start_time > timeout:
            raise TimeoutError(f"wait for block {begin_height + n} timeout")
    return cur_height


def wait_for_block(cli, height, timeout=240):
    for i in range(timeout * 2):
        try:
            status = cli.status()
        except AssertionError as e:
            print(f"get sync status failed: {e}", file=sys.stderr)
        else:
            current_height = int(get_sync_info(status)["latest_block_height"])
            print("current block height", current_height)
            if current_height >= height:
                break
        time.sleep(0.5)
    else:
        raise TimeoutError(f"wait for block {height} timeout")


def wait_for_port(port, host="127.0.0.1", timeout=40.0):
    print("wait for port", port, "to be available")
    start_time = time.perf_counter()
    while True:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                break
        except OSError as ex:
            time.sleep(0.1)
            if time.perf_counter() - start_time >= timeout:
                raise TimeoutError(
                    "Waited too long for the port {} on host {} to start accepting "
                    "connections.".format(port, host)
                ) from ex


def wait_for_url(url, timeout=40.0):
    print("wait for url", url, "to be available")
    start_time = time.perf_counter()
    while True:
        try:
            parsed = urlparse(url)
            host = parsed.hostname
            port = parsed.port
            with socket.create_connection((host, int(port or 80)), timeout=timeout):
                break
        except OSError as ex:
            time.sleep(0.1)
            if time.perf_counter() - start_time >= timeout:
                raise TimeoutError(
                    "Waited too long for the port {} on host {} to start accepting "
                    "connections.".format(port, host)
                ) from ex


def w3_wait_for_new_blocks(w3, n, sleep=0.5):
    begin_height = w3.eth.block_number
    while True:
        time.sleep(sleep)
        cur_height = w3.eth.block_number
        if cur_height - begin_height >= n:
            break


def supervisorctl(inipath, *args):
    return subprocess.check_output(
        (sys.executable, "-msupervisor.supervisorctl", "-c", inipath, *args),
    ).decode()


def find_log_event_attrs(events, ev_type, cond=None):
    for ev in events:
        if ev["type"] == ev_type:
            attrs = {attr["key"]: attr["value"] for attr in ev["attributes"]}
            if cond is None or cond(attrs):
                return attrs
    return None


def sign_transaction(w3, tx, key=KEYS["validator"]):
    "fill default fields and sign"
    acct = Account.from_key(key)
    tx["from"] = acct.address
    tx = fill_transaction_defaults(w3, tx)
    tx = fill_nonce(w3, tx)
    return acct.sign_transaction(tx)


def send_raw_transactions(w3, raw_transactions):
    with ThreadPoolExecutor(len(raw_transactions)) as exec:
        tasks = [
            exec.submit(w3.eth.send_raw_transaction, raw) for raw in raw_transactions
        ]
        sended_hash_set = {future.result() for future in as_completed(tasks)}
    return sended_hash_set


def send_transaction(w3, tx, key=KEYS["validator"]):
    signed = sign_transaction(w3, tx, key)
    txhash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return w3.eth.wait_for_transaction_receipt(txhash)


def send_txs(w3, cli, to, keys, params):
    tx = {"to": to, "value": 10000} | params
    # use different sender accounts to be able be send concurrently
    raw_transactions = []
    for key_from in keys:
        signed = sign_transaction(w3, tx, key_from)
        raw_transactions.append(signed.raw_transaction)

    # wait block update
    block_num_0 = wait_for_new_blocks(cli, 1, sleep=0.1)
    print(f"block number start: {block_num_0}")

    # send transactions
    sended_hash_set = send_raw_transactions(w3, raw_transactions)

    return block_num_0, sended_hash_set


def deploy_contract(w3, jsonfile, args=(), key=KEYS["validator"], exp_gas_used=None):
    """
    deploy contract and return the deployed contract instance
    """
    contract, _ = deploy_contract_with_receipt(w3, jsonfile, args, key, exp_gas_used)
    return contract


def deploy_contract_with_receipt(
    w3, jsonfile, args=(), key=KEYS["validator"], exp_gas_used=None
):
    """
    deploy contract and return the deployed contract instance and receipt
    """
    acct = Account.from_key(key)
    info = json.loads(jsonfile.read_text())
    bytecode = ""
    if "bytecode" in info:
        bytecode = info["bytecode"]
    if "byte" in info:
        bytecode = info["byte"]
    contract = w3.eth.contract(abi=info["abi"], bytecode=bytecode)
    tx = contract.constructor(*args).build_transaction({"from": acct.address})
    txreceipt = send_transaction(w3, tx, key)
    assert txreceipt.status == 1
    if exp_gas_used is not None:
        assert (
            exp_gas_used == txreceipt.gasUsed
        ), f"exp {exp_gas_used}, got {txreceipt.gasUsed}"
    address = txreceipt.contractAddress
    return w3.eth.contract(address=address, abi=info["abi"]), txreceipt


def get_contract(w3, address, jsonfile):
    info = json.loads(jsonfile.read_text())
    return w3.eth.contract(address=address, abi=info["abi"])


def create_contract_transaction(w3, jsonfile, args=(), key=KEYS["validator"]):
    """
    create contract transaction
    """
    acct = Account.from_key(key)
    info = json.loads(jsonfile.read_text())
    contract = w3.eth.contract(abi=info["abi"], bytecode=info["bytecode"])
    tx = contract.constructor(*args).build_transaction({"from": acct.address})
    return tx


def eth_to_bech32(addr, prefix=ADDRESS_PREFIX):
    bz = bech32.convertbits(HexBytes(addr), 8, 5)
    return bech32.bech32_encode(prefix, bz)


def decode_bech32(addr):
    _, bz = bech32.bech32_decode(addr)
    return HexBytes(bytes(bech32.convertbits(bz, 5, 8)))


def bech32_to_eth(addr):
    return to_checksum_address(decode_bech32(addr).hex())


def module_address(name):
    data = hashlib.sha256(name.encode()).digest()[:20]
    return to_checksum_address(decode_bech32(eth_to_bech32(data)).hex())


def get_balance(cli, name):
    try:
        addr = cli.address(name)
    except Exception as e:
        if "key not found" not in str(e):
            raise
        addr = name
    uom = cli.balance(addr)
    return uom


def assert_balance(cli, w3, name, evm=False):
    try:
        addr = cli.address(name)
    except Exception as e:
        if "key not found" not in str(e):
            raise
        addr = name
    uom = get_balance(cli, name)
    wei = w3.eth.get_balance(bech32_to_eth(addr))
    assert uom == wei // WEI_PER_UOM
    print(
        f"{name} contains uom: {uom}, om: {uom // UOM_PER_OM},",
        f"wei: {wei}, ether: {wei // WEI_PER_ETH}.",
    )
    return wei if evm else uom


def assert_transfer(cli, addr_a, addr_b, amt=1):
    balance_a = cli.balance(addr_a)
    balance_b = cli.balance(addr_b)
    rsp = cli.transfer(addr_a, addr_b, f"{amt}{DEFAULT_DENOM}")
    assert rsp["code"] == 0, rsp["raw_log"]
    res = find_log_event_attrs(rsp["events"], "tx", lambda attrs: "fee" in attrs)
    fee = int("".join(takewhile(lambda s: s.isdigit() or s == ".", res["fee"])))
    assert cli.balance(addr_a) == balance_a - amt - fee
    assert cli.balance(addr_b) == balance_b + amt


def recover_community(cli, tmp_path):
    return cli.create_account(
        "community",
        mnemonic=os.getenv("COMMUNITY_MNEMONIC"),
        home=tmp_path,
        coin_type=60,
    )["address"]


def transfer_via_cosmos(cli, from_addr, to_addr, amount):
    tx = cli.transfer(
        from_addr,
        to_addr,
        f"{amount}{DEFAULT_DENOM}",
        generate_only=True,
        chain_id=cli.chain_id,
    )
    tx_json = cli.sign_tx_json(
        tx, from_addr, home=cli.data_dir, node=cli.node_rpc, chain_id=cli.chain_id
    )
    rsp = cli.broadcast_tx_json(tx_json, home=cli.data_dir)
    assert rsp["code"] == 0, rsp["raw_log"]
    attrs = find_log_event_attrs(rsp["events"], "tx", lambda attrs: "fee" in attrs)
    return int("".join(takewhile(lambda s: s.isdigit() or s == ".", attrs["fee"])))


class ContractAddress(rlp.Serializable):
    fields = [
        ("from", rlp.sedes.Binary()),
        ("nonce", rlp.sedes.big_endian_int),
    ]


def contract_address(addr, nonce):
    return eth_utils.to_checksum_address(
        eth_utils.to_hex(
            eth_utils.keccak(
                rlp.encode(ContractAddress(eth_utils.to_bytes(hexstr=addr), nonce))
            )[12:]
        )
    )


def build_batch_tx(w3, cli, txs, key=KEYS["validator"]):
    "return cosmos batch tx and eth tx hashes"
    signed_txs = [sign_transaction(w3, tx, key) for tx in txs]
    tmp_txs = [cli.build_evm_tx(f"0x{s.raw_transaction.hex()}") for s in signed_txs]

    msgs = [tx["body"]["messages"][0] for tx in tmp_txs]
    fee = sum(int(tx["auth_info"]["fee"]["amount"][0]["amount"]) for tx in tmp_txs)
    gas_limit = sum(int(tx["auth_info"]["fee"]["gas_limit"]) for tx in tmp_txs)

    tx_hashes = [signed.hash for signed in signed_txs]

    # build batch cosmos tx
    return {
        "body": {
            "messages": msgs,
            "memo": "",
            "timeout_height": "0",
            "extension_options": [
                {"@type": "/cosmos.evm.vm.v1.ExtensionOptionsEthereumTx"}
            ],
            "non_critical_extension_options": [],
        },
        "auth_info": {
            "signer_infos": [],
            "fee": {
                "amount": [{"denom": "aom", "amount": str(fee)}],
                "gas_limit": str(gas_limit),
                "payer": "",
                "granter": "",
            },
        },
        "signatures": [],
    }, tx_hashes


def approve_proposal(n, events, event_query_tx=False):
    cli = n.cosmos_cli()

    # get proposal_id
    ev = find_log_event_attrs(
        events, "submit_proposal", lambda attrs: "proposal_id" in attrs
    )
    proposal_id = ev["proposal_id"]
    for i in range(len(n.config["validators"])):
        rsp = n.cosmos_cli(i).gov_vote(
            "validator", proposal_id, "yes", event_query_tx, gas_prices="0.8uom"
        )
        assert rsp["code"] == 0, rsp["raw_log"]
    wait_for_new_blocks(cli, 1)
    res = cli.query_tally(proposal_id)
    res = res.get("tally") or res
    assert (
        int(res["yes_count"]) == cli.staking_pool()
    ), "all validators should have voted yes"
    print("wait for proposal to be activated")
    proposal = cli.query_proposal(proposal_id)
    wait_for_block_time(cli, isoparse(proposal["voting_end_time"]))
    proposal = cli.query_proposal(proposal_id)
    assert proposal["status"] == "PROPOSAL_STATUS_PASSED", proposal


def submit_any_proposal(mantra, tmp_path):
    # governance module account as granter
    cli = mantra.cosmos_cli()
    granter_addr = eth_to_bech32(module_address("gov"))
    grantee_addr = cli.address("signer1")

    # this json can be obtained with `--generate-only` flag for respective cli calls
    proposal_json = {
        "messages": [
            {
                "@type": "/cosmos.feegrant.v1beta1.MsgGrantAllowance",
                "granter": granter_addr,
                "grantee": grantee_addr,
                "allowance": {
                    "@type": "/cosmos.feegrant.v1beta1.BasicAllowance",
                    "spend_limit": [],
                    "expiration": None,
                },
            }
        ],
        "deposit": f"1{DEFAULT_DENOM}",
        "title": "title",
        "summary": "summary",
    }
    proposal_file = tmp_path / "proposal.json"
    proposal_file.write_text(json.dumps(proposal_json))
    rsp = cli.submit_gov_proposal(proposal_file, from_="community")
    assert rsp["code"] == 0, rsp["raw_log"]
    approve_proposal(mantra, rsp["events"])
    grant_detail = cli.query_grant(granter_addr, grantee_addr)
    assert grant_detail["granter"] == granter_addr
    assert grant_detail["grantee"] == grantee_addr


def submit_gov_proposal(mantra, tmp_path, **kwargs):
    proposal = tmp_path / "proposal.json"
    proposal_src = {
        "title": "title",
        "summary": "summary",
        "deposit": f"1{DEFAULT_DENOM}",
        **kwargs,
    }
    proposal.write_text(json.dumps(proposal_src))
    rsp = mantra.cosmos_cli().submit_gov_proposal(proposal, from_="community")
    assert rsp["code"] == 0, rsp["raw_log"]
    approve_proposal(mantra, rsp["events"])
    print("check params have been updated now")


def derive_new_account(n=1):
    # derive a new address
    account_path = f"m/44'/60'/0'/0/{n}"
    mnemonic = os.getenv("SIGNER1_MNEMONIC")
    return Account.from_mnemonic(mnemonic, account_path=account_path)


def edit_ini_sections(chain_id, ini_path, callback):
    ini = configparser.RawConfigParser()
    ini.read(ini_path)
    reg = re.compile(rf"^program:{chain_id}-node(\d+)")
    for section in ini.sections():
        m = reg.match(section)
        if m:
            i = m.group(1)
            old = ini[section]
            ini[section].update(callback(i, old))
    with ini_path.open("w") as fp:
        ini.write(fp)


def adjust_base_fee(parent_fee, gas_limit, gas_used, params={}):
    "spec: https://eips.ethereum.org/EIPS/eip-1559#specification"
    change_denominator = params.get("base_fee_change_denominator", 8)
    elasticity_multiplier = params.get("elasticity_multiplier", 2)
    gas_target = gas_limit // elasticity_multiplier
    if gas_used == gas_target:
        return parent_fee
    delta = parent_fee * abs(gas_target - gas_used) // gas_target // change_denominator
    # https://github.com/cosmos/evm/blob/0e511d32206b1ac709a0eb0ddb1aa21d29e833b8/x/feemarket/keeper/eip1559.go#L93
    if gas_target > gas_used:
        min_gas_price = float(params.get("min_gas_price", 0)) * WEI_PER_UOM
        return max(parent_fee - delta, min_gas_price)
    else:
        return parent_fee + max(delta, 1)

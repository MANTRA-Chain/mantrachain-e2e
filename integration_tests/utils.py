import asyncio
import base64
import binascii
import configparser
import datetime
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import takewhile
from pathlib import Path

import bech32
import eth_utils
import jsonmerge
import requests
import rlp
import solcx
import web3
from dateutil.parser import isoparse
from dotenv import load_dotenv
from eth_account import Account
from eth_account.signers.base import BaseAccount
from eth_contract.contract import Contract as ContractAsync
from eth_contract.create2 import create2_address
from eth_contract.deploy_utils import (
    ensure_create2_deployed,
    ensure_deployed_by_create2,
)
from eth_contract.erc20 import ERC20
from eth_contract.utils import ZERO_ADDRESS, balance_of, get_initcode
from eth_contract.utils import send_transaction as send_transaction_async
from eth_contract.weth import WETH, WETH9_ARTIFACT
from eth_utils import to_checksum_address
from hexbytes import HexBytes
from pystarport import cluster
from pystarport.utils import (
    wait_for_block_time,
    wait_for_fn,
    wait_for_new_blocks,
)
from web3 import AsyncWeb3
from web3._utils.transactions import fill_nonce, fill_transaction_defaults

load_dotenv(Path(__file__).parent.parent / "scripts/.env")
Account.enable_unaudited_hdwallet_features()
MNEMONICS = {
    "validator": os.getenv("VALIDATOR1_MNEMONIC"),
    "validator2": os.getenv("VALIDATOR2_MNEMONIC"),
    "validator3": os.getenv("VALIDATOR3_MNEMONIC"),
    "community": os.getenv("COMMUNITY_MNEMONIC"),
    "signer1": os.getenv("SIGNER1_MNEMONIC"),
    "signer2": os.getenv("SIGNER2_MNEMONIC"),
    "reserve": os.getenv("RESERVE_MNEMONIC"),
}
ACCOUNTS = {
    name: Account.from_mnemonic(mnemonic) for name, mnemonic in MNEMONICS.items()
}
KEYS = {name: account.key for name, account in ACCOUNTS.items()}
ADDRS = {name: account.address for name, account in ACCOUNTS.items()}

DEFAULT_DENOM = os.getenv("EVM_DENOM", "amantra")
DEFAULT_EXTENDED_DENOM = os.getenv("EVM_EXTENDED_DENOM", "amantra")
CHAIN_ID = os.getenv("CHAIN_ID", "mantra-canary-net-1")
EVM_CHAIN_ID = int(os.getenv("EVM_CHAIN_ID", 7888))
# the default initial base fee used by integration tests
DEFAULT_GAS_AMT = float(os.getenv("DEFAULT_GAS_AMT", 40000000000))
DEFAULT_GAS_PRICE = f"{DEFAULT_GAS_AMT}{DEFAULT_DENOM}"
DEFAULT_GAS = 200000
WEI_PER_ETH = 10**18  # 10^18 wei == 1 ether
WEI_PER_DENOM = int(os.getenv("WEI_PER_DENOM", 1))  # 1 wei == 1 amantra
ADDRESS_PREFIX = os.getenv("ADDRESS_PREFIX", "mantra")
CMD = os.getenv("CMD", "mantrachaind")
SCALE_FACTOR = 4_000_000_000_000


WETH_SALT = 999
WETH_ADDRESS = create2_address(get_initcode(WETH9_ARTIFACT), WETH_SALT)

MockERC20_ARTIFACT = json.loads(
    Path(__file__).parent.joinpath("contracts/contracts/MockERC20.json").read_text()
)


class AsyncContract:
    def __init__(self, name, key=KEYS["community"]):
        self.acct = Account.from_key(key)
        self.name = name
        self.contract = None
        self.address = None
        self.w3 = None

    async def deploy(self, w3: AsyncWeb3, args=()):
        if self.contract:
            return self.address
        self.w3 = w3
        res = build_contract(self.name)
        tx = await create_contract_transaction(w3, res, args, key=self.acct.key)
        receipt = await send_transaction_async(w3, self.acct, **tx)
        self.contract = ContractAsync(res["abi"])
        self.address = receipt.contractAddress
        return self.address

    def _check_deployed(self):
        if not self.contract:
            raise ValueError("Contract not deployed yet")


class AsyncGreeter(AsyncContract):
    def __init__(self, key=KEYS["community"]):
        super().__init__("Greeter", key)

    async def greet(self, block_identifier=None):
        self._check_deployed()
        return await self.contract.fns.greet().call(
            self.w3, to=self.address, block_identifier=block_identifier
        )

    async def int_value(self):
        self._check_deployed()
        return await self.contract.fns.intValue().call(self.w3, to=self.address)

    async def set_greeting(self, message: str):
        self._check_deployed()
        return await self.contract.fns.setGreeting(message).transact(
            self.w3, self.acct, to=self.address
        )


class AsyncTestRevert(AsyncContract):
    def __init__(self, key=KEYS["community"]):
        super().__init__("TestRevert", key)

    async def transfer(self, value):
        self._check_deployed()
        return await self.contract.fns.transfer(value).transact(
            self.w3,
            self.acct,
            to=self.address,
            gas=100000,  # skip estimateGas error
        )


class AsyncTestMessageCall(AsyncContract):
    def __init__(self, key=KEYS["community"]):
        super().__init__("TestMessageCall", key)

    async def test(self, iterations):
        self._check_deployed()
        return await self.contract.fns.test(iterations).transact(
            self.w3, self.acct, to=self.address
        )

    def get_test_data(self, iterations):
        self._check_deployed()
        return self.contract.fns.test(iterations).data


class Contract:
    def __init__(self, name, private_key=KEYS["community"], chain_id=EVM_CHAIN_ID):
        self.chain_id = chain_id
        self.account = Account.from_key(private_key)
        self.owner = self.account.address
        self.private_key = private_key
        res = build_contract(name)
        self.bytecode = res["bytecode"]
        self.code = res["code"]
        self.abi = res["abi"]
        self.contract = None
        self.w3 = None

    def deploy(self, w3, exp_gas_used=None):
        "Deploy contract on `w3` and return the receipt."
        if self.contract is None:
            self.w3 = w3
            contract = self.w3.eth.contract(abi=self.abi, bytecode=self.bytecode)
            transaction = contract.constructor().build_transaction(
                {"chainId": self.chain_id, "from": self.owner}
            )
            receipt = send_transaction(self.w3, transaction, self.private_key)
            if exp_gas_used is not None:
                assert (
                    exp_gas_used == receipt.gasUsed
                ), f"exp {exp_gas_used}, got {receipt.gasUsed}"
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
                "from": self.owner,
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
                "from": self.owner,
                "gas": 100000,  # skip estimateGas error
            }
        )
        receipt = send_transaction(self.w3, transaction, self.private_key)
        return receipt


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


def find_duplicate(attributes):
    res = set()
    key = attributes[0]["key"]
    for attribute in attributes:
        if attribute["key"] == key:
            value0 = attribute["value"]
        elif attribute["key"] == "amount":
            amount = attribute["value"]
            value_pair = f"{value0}:{amount}"
            if value_pair in res:
                return value_pair
            res.add(value_pair)
    return None


def sign_transaction(w3, tx, key=KEYS["community"]):
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


def send_transaction(w3, tx, key=KEYS["community"], check=True):
    signed = sign_transaction(w3, tx, key)
    txhash = w3.eth.send_raw_transaction(signed.raw_transaction)
    if check:
        return w3.eth.wait_for_transaction_receipt(txhash)
    return txhash


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


# Global cache for built contracts
CONTRACTS = {}


def build_contract_solcx(name, dir="contracts"):
    source = (Path(__file__).parent / f"contracts/{dir}/{name}.sol").read_text()
    input_json = {
        "language": "Solidity",
        "sources": {"<stdin>": {"content": source}},
        "settings": {
            "outputSelection": {
                "*": {
                    "*": [
                        "abi",
                        "evm.bytecode",
                        "evm.deployedBytecode",
                        "evm.methodIdentifiers",
                    ]
                }
            },
            "optimizer": {"enabled": True, "runs": 200},
            "evmVersion": "istanbul",
        },
    }
    output = solcx.compile_standard(
        input_json, solc_version="0.8.0", solc_binary="solc"
    )
    output = output["contracts"]["<stdin>"]

    # collapse "evm" field for easier access
    for name in output:
        contract = output[name]
        contract.update(contract.pop("evm"))

    return output


def selectors(artifact) -> list[bytes]:
    return [HexBytes(sel) for sel in artifact["methodIdentifiers"].values()]


def build_contract(name, dir="contracts", contract=None) -> dict:
    contract = contract or name
    if contract in CONTRACTS:
        return CONTRACTS[contract]
    cmd = [
        "solc",
        "--abi",
        "--bin",
        "--bin-runtime",
        f"contracts/{dir}/{name}.sol",
        "-o",
        "build",
        "--overwrite",
        "--optimize",
        "--optimize-runs",
        "100000",
        "--via-ir",
        "--metadata-hash",
        "none",
        "--no-cbor-metadata",
        "--base-path",
        "./contracts",
        # "$(cat contracts/remappings.txt)",
    ]
    with open("contracts/remappings.txt", "r") as f:
        remappings = f.read().strip().split()

    cmd.extend(remappings)
    print(*cmd)
    subprocess.run(cmd, check=True)
    bytecode = Path(f"build/{contract}.bin").read_text().strip()
    code = Path(f"build/{contract}.bin-runtime").read_text().strip()
    result = {
        "abi": json.loads(Path(f"build/{contract}.abi").read_text()),
        "bytecode": f"0x{bytecode}",
        "code": f"0x{code}",
    }
    CONTRACTS[contract] = result
    return result


async def build_and_deploy_contract_async(
    w3: AsyncWeb3,
    name,
    args=(),
    key=KEYS["community"],
    dir="contracts",
    contract=None,
):
    res = build_contract(name, dir=dir, contract=contract)
    tx = await create_contract_transaction(w3, res, args, key, dir=dir)
    txreceipt = await send_transaction_async(w3, Account.from_key(key), **tx)
    return w3.eth.contract(address=txreceipt.contractAddress, abi=res["abi"])


def create_contract_transaction(
    w3, name_or_res, args=(), key=KEYS["community"], dir="contracts"
):
    acct = Account.from_key(key)
    if isinstance(name_or_res, str):
        res = build_contract(name_or_res, dir=dir)
    else:
        res = name_or_res
    contract = w3.eth.contract(abi=res["abi"], bytecode=res["bytecode"])
    return contract.constructor(*args).build_transaction({"from": acct.address})


def eth_to_bech32(addr, prefix=ADDRESS_PREFIX):
    bz = bech32.convertbits(HexBytes(addr), 8, 5)
    return bech32.bech32_encode(prefix, bz)


def decode_bech32(addr):
    _, bz = bech32.bech32_decode(addr)
    return HexBytes(bytes(bech32.convertbits(bz, 5, 8)))


def bech32_to_eth(addr):
    return to_checksum_address(decode_bech32(addr).hex())


def hash_func(address_type_bytes, key):
    hasher = hashlib.sha256()
    hasher.update(address_type_bytes)
    th = hasher.digest()
    hasher = hashlib.sha256()
    hasher.update(th)
    hasher.update(key)
    return hasher.digest()


def derive(address_type_bytes, key):
    return hash_func(address_type_bytes, key)


def module_address(name, *derivation_keys):
    m_key = name.encode()
    if len(derivation_keys) == 0:
        address_bytes = hashlib.sha256(m_key).digest()[:20]
    else:
        m_key = m_key + b"\x00"
        first_key = m_key + derivation_keys[0]
        addr = hash_func("module".encode(), first_key)
        for k in derivation_keys[1:]:
            addr = derive(addr, k)
        address_bytes = addr[:20]
    eth_address = "0x" + address_bytes.hex()
    return eth_to_bech32(eth_address)


def generate_isolated_address(channel_id, sender):
    name = "ibc-callbacks"
    return module_address(name, channel_id.encode(), sender.encode())


def get_balance(cli, name):
    try:
        addr = cli.address(name, skip_create=True)
    except Exception as e:
        if "key not found" not in str(e):
            raise
        addr = name
    return cli.balance(addr)


def assert_balance(cli, w3, name, evm=False):
    try:
        addr = cli.address(name, skip_create=True)
    except Exception as e:
        if "key not found" not in str(e):
            raise
        addr = name
    balance = get_balance(cli, name)
    wei = w3.eth.get_balance(bech32_to_eth(addr))
    assert balance == wei // WEI_PER_DENOM
    print(
        f"wei: {wei}, ether: {wei // WEI_PER_ETH}.",
    )
    return wei if evm else balance


def find_fee(rsp):
    res = find_log_event_attrs(rsp["events"], "tx", lambda attrs: "fee" in attrs)
    return int("".join(takewhile(lambda s: s.isdigit() or s == ".", res["fee"])))


def assert_transfer(cli, addr_a, addr_b, amt=1, denom=DEFAULT_DENOM, **kwargs):
    balance_a = cli.balance(addr_a, denom=denom)
    balance_b = cli.balance(addr_b, denom=denom)
    rsp = cli.transfer(addr_a, addr_b, f"{amt}{denom}", **kwargs)
    assert rsp["code"] == 0, rsp["raw_log"]
    fee = find_fee(rsp)
    assert cli.balance(addr_a, denom=denom) == balance_a - amt - fee
    assert cli.balance(addr_b, denom=denom) == balance_b + amt


def denom_to_erc20_address(denom):
    denom_hash = hashlib.sha256(denom.encode()).digest()
    return to_checksum_address("0x" + denom_hash[-20:].hex())


def escrow_address(port, channel, prefix=ADDRESS_PREFIX):
    escrow_addr_version = "ics20-1"
    pre_image = f"{escrow_addr_version}\x00{port}/{channel}"
    return eth_to_bech32(
        hashlib.sha256(pre_image.encode()).digest()[:20].hex(), prefix=prefix
    )


def ibc_denom_address(denom):
    if not denom.startswith("ibc/"):
        raise ValueError(f"coin {denom} does not have 'ibc/' prefix")
    if len(denom) < 5 or denom[4:].strip() == "":
        raise ValueError(f"coin {denom} is not a valid IBC voucher hash")
    hash_part = denom[4:]  # remove "ibc/" prefix
    hash_bytes = binascii.unhexlify(hash_part)
    return to_checksum_address("0x" + hash_bytes[-20:].hex())


def retry_on_seq_mismatch(fn, *args, max_retries=3, **kwargs):
    for attempt in range(max_retries):
        rsp = fn(*args, **kwargs)
        if rsp["code"] == 0:
            return rsp
        if rsp["code"] == 32 and "account sequence mismatch" in rsp["raw_log"]:
            if attempt < max_retries - 1:
                continue
        return rsp
    return rsp


async def retry_on_nonce_mismatch(fn, *args, max_retries=3, **kwargs):
    for attempt in range(max_retries):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            error_msg = str(e).lower()
            # Handle nonce mismatch errors
            should_retry = "nonce" in error_msg and (
                "lower" in error_msg or "invalid" in error_msg
            )
            # Handle "already known" errors (transaction already in mempool)
            should_retry = should_retry or ("already known" in error_msg)

            if should_retry and attempt < max_retries - 1:
                # Wait a bit longer for "already known" errors
                wait_time = 2.0 if "already known" in error_msg else 1.0
                await asyncio.sleep(wait_time)
                continue
            raise e
    return None


def call_with_retry(fn, expect_error=False, max_retries=3, retry_delay=0.1):
    for attempt in range(1, max_retries + 1):
        try:
            fn()
            if expect_error:
                print(f"no error but query succeeded on attempt {attempt}")
                return False
            print(f"query successful on attempt {attempt}")
            return True
        except web3.exceptions.Web3RPCError as e:
            error_str = str(e)
            if "Error while dialing" in error_str or "connection refused" in error_str:
                if expect_error:
                    return True
                if attempt == max_retries:
                    print(f"failed after {max_retries} attempts")
                    return False
                time.sleep(retry_delay)
            else:
                raise
    return False


async def call_with_retry_async(fn, expect_error=False, max_retries=3, retry_delay=0.1):
    for attempt in range(1, max_retries + 1):
        try:
            await fn()
            if expect_error:
                print(f"no error but query succeeded on attempt {attempt}")
                return False
            print(f"query successful on attempt {attempt}")
            return True
        except web3.exceptions.Web3RPCError as e:
            error_str = str(e)
            if "Error while dialing" in error_str or "connection refused" in error_str:
                if expect_error:
                    return True
                if attempt == max_retries:
                    print(f"failed after {max_retries} attempts")
                    return False
                await asyncio.sleep(retry_delay)
            else:
                raise
    return False


def assert_create_tokenfactory_denom(cli, subdenom, is_legacy=False, **kwargs):
    # check create tokenfactory denom
    rsp = retry_on_seq_mismatch(cli.create_tokenfactory_denom, subdenom, **kwargs)
    assert rsp["code"] == 0, rsp["raw_log"]
    event = find_log_event_attrs(
        rsp["events"], "create_denom", lambda attrs: "creator" in attrs
    )
    sender = kwargs.get("_from")
    rsp = cli.query_tokenfactory_denoms(sender)
    denom = f"factory/{sender}/{subdenom}"
    assert denom in rsp.get("denoms"), rsp
    expected = {"creator": sender, "new_token_denom": denom}
    erc20_address = None
    if not is_legacy:
        erc20_address = denom_to_erc20_address(denom)
        expected["new_token_eth_addr"] = erc20_address
        pair = cli.query_erc20_token_pair(denom)
        assert pair == {
            "erc20_address": erc20_address,
            "denom": denom,
            "enabled": True,
            "contract_owner": "OWNER_MODULE",
        }
    assert expected.items() <= event.items()
    meta = {"denom_units": [{"denom": denom}], "base": denom}
    if not is_legacy:
        # all missing metadata fields fixed in rc3
        meta["name"] = denom
        meta["display"] = denom
        meta["symbol"] = denom
    assert meta.items() <= cli.query_bank_denom_metadata(denom).items()
    _from = None if is_legacy else sender
    rsp = cli.query_denom_authority_metadata(denom, _from=_from).get("Admin")
    assert rsp == sender, rsp
    return denom


def assert_mint_tokenfactory_denom(cli, denom, amt, is_legacy=False, **kwargs):
    # check mint tokenfactory denom
    sender = kwargs.get("_from")
    balance = cli.balance(sender, denom)
    coin = f"{amt}{denom}"
    rsp = retry_on_seq_mismatch(cli.mint_tokenfactory_denom, coin, **kwargs)
    assert rsp["code"] == 0, rsp["raw_log"]
    if not is_legacy:
        event = find_log_event_attrs(
            rsp["events"], "tf_mint", lambda attrs: "mint_to_address" in attrs
        )
        expected = {
            "mint_to_address": sender,
            "amount": coin,
        }
        assert expected.items() <= event.items()
    current = cli.balance(sender, denom)
    assert current == balance + amt
    return current


def assert_transfer_tokenfactory_denom(cli, denom, receiver, amt, **kwargs):
    # check transfer tokenfactory denom
    sender = kwargs.get("_from")
    balance = cli.balance(sender, denom)
    rsp = cli.transfer(sender, receiver, f"{amt}{denom}", **kwargs)
    assert rsp["code"] == 0, rsp["raw_log"]
    current = cli.balance(sender, denom)
    assert current == balance - amt
    return current


def assert_burn_tokenfactory_denom(cli, denom, amt, **kwargs):
    # check burn tokenfactory denom
    sender = kwargs.get("_from")
    balance = cli.balance(sender, denom)
    coin = f"{amt}{denom}"
    rsp = cli.burn_tokenfactory_denom(coin, **kwargs)
    assert rsp["code"] == 0, rsp["raw_log"]
    event = find_log_event_attrs(
        rsp["events"], "tf_burn", lambda attrs: "burn_from_address" in attrs
    )
    expected = {
        "burn_from_address": sender,
        "amount": coin,
    }
    assert expected.items() <= event.items()
    current = cli.balance(sender, denom)
    assert current == balance - amt
    return current


def assert_set_tokenfactory_denom(cli, tmp_path, denom, **kwargs):
    sender = kwargs.get("_from")
    name = "Dubai"
    symbol = "DLD"
    meta = {
        "description": name,
        "denom_units": [{"denom": denom}, {"denom": symbol, "exponent": 6}],
        "base": denom,
        "display": symbol,
        "name": name,
        "symbol": symbol,
    }
    file_meta = Path(tmp_path) / "meta.json"
    file_meta.write_text(json.dumps(meta))
    rsp = cli.set_tokenfactory_denom(file_meta, **kwargs)
    assert rsp["code"] == 0, rsp["raw_log"]
    assert cli.query_bank_denom_metadata(denom) == meta
    rsp = cli.query_denom_authority_metadata(denom).get("Admin")
    assert rsp == sender, rsp


def recover_community(cli, tmp_path):
    return cli.create_account(
        "community",
        mnemonic=os.getenv("COMMUNITY_MNEMONIC"),
        home=tmp_path,
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


def build_batch_tx(w3, cli, txs, key=KEYS["community"]):
    "return cosmos batch tx and eth tx hashes"
    signed_txs = [sign_transaction(w3, tx, key) for tx in txs]
    tmp_txs = [
        cli.build_evm_tx(f"0x{s.raw_transaction.hex()}", chain_id=EVM_CHAIN_ID)
        for s in signed_txs
    ]

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
                "amount": [{"denom": DEFAULT_EXTENDED_DENOM, "amount": str(fee)}],
                "gas_limit": str(gas_limit),
                "payer": "",
                "granter": "",
            },
        },
        "signatures": [],
    }, tx_hashes


def approve_proposal(n, events, event_query_tx=True, **kwargs):
    cli = n.cosmos_cli()
    # get proposal_id
    ev = find_log_event_attrs(
        events, "submit_proposal", lambda attrs: "proposal_id" in attrs
    )
    proposal_id = ev["proposal_id"]
    for i in range(len(n.config["validators"])):
        node = n.config["validators"][i]
        # skip fullnodes
        if "staked" not in node:
            continue
        account_name = node.get("name", "validator")
        rsp = n.cosmos_cli(i).gov_vote(
            account_name,
            proposal_id,
            "yes",
            event_query_tx=event_query_tx,
            **kwargs,
        )
        assert rsp["code"] == 0, rsp["raw_log"]
    wait_for_new_blocks(cli, 1)
    res = cli.query_tally(proposal_id)
    res = res.get("tally") or res
    assert (
        int(res["yes_count"]) == cli.staking_pool()
    ), "all validators should have voted yes"
    proposal = cli.query_proposal(proposal_id)
    end = isoparse(proposal["voting_end_time"])
    print(f"wait for proposal to be activated after {end}")
    height_bf = cli.block_height()
    wait_for_block_time(cli, end, sleep=0.01)
    height_af = cli.block_height()
    proposal = cli.query_proposal(proposal_id)
    assert proposal["status"] == "PROPOSAL_STATUS_PASSED", proposal
    return [height_bf, height_af]


def submit_gov_proposal(mantra, tmp_path, messages, event_query_tx=True, **kwargs):
    proposal = tmp_path / "proposal.json"
    proposal_src = {
        "title": "title",
        "summary": "summary",
        "deposit": f"1{DEFAULT_DENOM}",
        "messages": messages,
    }
    proposal.write_text(json.dumps(proposal_src))
    rsp = mantra.cosmos_cli().submit_gov_proposal(proposal, from_="community", **kwargs)
    assert rsp["code"] == 0, rsp["raw_log"]
    heights = approve_proposal(mantra, rsp["events"], event_query_tx=event_query_tx)
    print(f"check params have been updated now after {heights}")
    return heights


def create_periodic_vesting_acct(cli, tmp_path, coin, **kwargs):
    start_time = int(time.time())
    periods = tmp_path / "periods.json"
    src = {
        "start_time": start_time,
        "periods": [{"coins": coin, "length_seconds": 2592000}],
    }
    periods.write_text(json.dumps(src))
    name = f"periodic_vesting{start_time}"
    addr = cli.create_account(name)["address"]
    rsp = cli.create_periodic_vesting_account(addr, periods, **kwargs)
    assert rsp["code"] == 0, rsp["raw_log"]
    return addr


def derive_new_account(n=1, mnemonic="SIGNER1_MNEMONIC"):
    # derive a new address
    account_path = f"m/44'/60'/0'/0/{n}"
    return Account.from_mnemonic(os.getenv(mnemonic), account_path=account_path)


def derive_random_account():
    return derive_new_account(secrets.randbelow(10000) + 1)


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


def adjust_base_fee(parent_fee, gas_limit, gas_used, params):
    "spec: https://eips.ethereum.org/EIPS/eip-1559#specification"
    params = {k: float(v) for k, v in params.items()}
    change_denominator = params.get("base_fee_change_denominator", 8)
    elasticity_multiplier = params.get("elasticity_multiplier", 2)
    gas_target = gas_limit // elasticity_multiplier
    if gas_used == gas_target:
        return parent_fee
    delta = parent_fee * abs(gas_target - gas_used) // gas_target // change_denominator
    # https://github.com/cosmos/evm/blob/0e511d32206b1ac709a0eb0ddb1aa21d29e833b8/x/feemarket/keeper/eip1559.go#L93
    if gas_target > gas_used:
        min_gas_price = float(params.get("min_gas_price", 0)) * WEI_PER_DENOM
        return max(parent_fee - delta, min_gas_price)
    else:
        return parent_fee + max(delta, 1)


def assert_duplicate(rpc, height):
    res = requests.get(f"{rpc}/block_results?height={height}").json().get("result")
    res = next((tx for tx in res.get("txs_results") if tx["code"] == 0), None)
    values = set()
    for event in res.get("events", []):
        if event["type"] != "transfer":
            continue
        str = json.dumps(event)
        assert str not in values, f"dup event find: {str}"
        values.add(str)


def fund_acc(w3, acc, fund=4_000_000_000_000_000_000):
    addr = acc.address
    if w3.eth.get_balance(addr, "latest") == 0:
        tx = {"to": addr, "value": fund, "gasPrice": w3.eth.gas_price}
        send_transaction(w3, tx)
        assert w3.eth.get_balance(addr, "latest") == fund


def do_multisig(cli, tmp_path, signer1_name, signer2_name, multisig_name):
    # prepare multisig and accounts
    signer1 = cli.address(signer1_name)
    signer2 = cli.address(signer2_name)
    cli.make_multisig(multisig_name, signer1_name, signer2_name)
    multi_addr = cli.address(multisig_name)
    amt = 9_000_000_000_000_000 // WEI_PER_DENOM
    rsp = cli.transfer(signer1, multi_addr, f"{amt}{DEFAULT_DENOM}")
    assert rsp["code"] == 0, rsp["raw_log"]
    acc = cli.account(multi_addr)
    res = cli.account_by_num(acc["account"]["value"]["account_number"])
    assert res["account_address"] == multi_addr

    m_txt = tmp_path / "m.json"
    p1_txt = tmp_path / "p1.json"
    p2_txt = tmp_path / "p2.json"
    tx_txt = tmp_path / "tx.json"
    amt = 1
    multi_tx = cli.transfer(
        multi_addr,
        signer2,
        f"{amt}{DEFAULT_DENOM}",
        generate_only=True,
    )
    json.dump(multi_tx, m_txt.open("w"))
    signature1 = cli.sign_multisig_tx(m_txt, multi_addr, signer1_name)
    json.dump(signature1, p1_txt.open("w"))
    signature2 = cli.sign_multisig_tx(m_txt, multi_addr, signer2_name)
    json.dump(signature2, p2_txt.open("w"))
    final_multi_tx = cli.combine_multisig_tx(
        m_txt,
        multisig_name,
        p1_txt,
        p2_txt,
    )
    json.dump(final_multi_tx, tx_txt.open("w"))
    rsp = cli.broadcast_tx(tx_txt)
    assert rsp["code"] == 0, rsp["raw_log"]
    assert cli.account(multi_addr)["account"]["value"]["address"] == multi_addr


def decode_base64(raw):
    try:
        return base64.b64decode(raw.encode()).decode()
    except Exception:
        return raw


def parse_events_rpc(events):
    result = defaultdict(dict)
    for ev in events:
        for attr in ev["attributes"]:
            if attr["key"] is None:
                continue
            key = decode_base64(attr["key"])
            if attr["value"] is not None:
                value = decode_base64(attr["value"])
            else:
                value = None
            result[ev["type"]][key] = value
    return result


async def assert_create_erc20_denom(w3, signer):
    await ensure_create2_deployed(w3, signer)
    await ensure_deployed_by_create2(
        w3, signer, get_initcode(WETH9_ARTIFACT), salt=WETH_SALT
    )
    assert (await ERC20.fns.decimals().call(w3, to=WETH_ADDRESS)) == 18
    total_bf = await ERC20.fns.totalSupply().call(w3, to=WETH_ADDRESS)
    balance_bf = await ERC20.fns.balanceOf(signer).call(w3, to=WETH_ADDRESS)
    assert total_bf == balance_bf

    weth = WETH(to=WETH_ADDRESS)
    erc20_denom = f"erc20:{WETH_ADDRESS}"
    deposit_amt = 100
    res = await weth.fns.deposit().transact(w3, signer, value=deposit_amt)
    assert res.status == 1
    total = await ERC20.fns.totalSupply().call(w3, to=WETH_ADDRESS)
    balance = await ERC20.fns.balanceOf(signer).call(w3, to=WETH_ADDRESS)
    assert total == balance
    assert (total - total_bf) == (balance - balance_bf) == deposit_amt
    return erc20_denom, total


async def assert_weth_flow(w3, weth_addr, owner, account):
    weth = WETH(to=weth_addr)
    before = await balance_of(w3, ZERO_ADDRESS, owner)
    receipt = await weth.fns.deposit().transact(w3, account, value=1000)
    fee = receipt["effectiveGasPrice"] * receipt["gasUsed"]
    await balance_of(w3, weth_addr, owner) == 1000
    receipt = await weth.fns.withdraw(1000).transact(w3, account)
    fee += receipt["effectiveGasPrice"] * receipt["gasUsed"]
    await balance_of(w3, weth_addr, owner) == 0
    assert await balance_of(w3, ZERO_ADDRESS, owner) == before - fee
    assert await weth.fns.decimals().call(w3) == 18
    assert await weth.fns.symbol().call(w3) == "WETH"
    assert await weth.fns.name().call(w3) == "Wrapped Ether"


def address_to_bytes32(addr) -> HexBytes:
    return HexBytes(addr).rjust(32, b"\x00")


def assert_approval_log(receipt, owner, spender, expected):
    approval_topic = HexBytes(ERC20.events.Approval.topic.hex())
    approval_logs = [
        log for log in receipt["logs"] if log["topics"][0] == approval_topic
    ]
    assert len(approval_logs) == 1
    approval_log = approval_logs[0]
    assert approval_log["topics"][1] == address_to_bytes32(owner), "owner mismatch"
    assert approval_log["topics"][2] == address_to_bytes32(spender), "spender mismatch"
    return int.from_bytes(approval_log["data"], "big") == expected


async def assert_tf_flow(w3, receiver, signer1, signer2, tf_erc20_addr):
    # signer1 transfer 5tf_erc20 to receiver
    transfer_amt = 5
    signer1_balance_bf = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    signer2_balance_bf = await ERC20.fns.balanceOf(signer2).call(w3, to=tf_erc20_addr)
    receiver_balance_bf = await ERC20.fns.balanceOf(receiver).call(w3, to=tf_erc20_addr)
    assert signer1_balance_bf >= transfer_amt

    await retry_on_nonce_mismatch(
        ERC20.fns.transfer(receiver, transfer_amt).transact,
        w3,
        signer1,
        to=tf_erc20_addr,
        gasPrice=(await w3.eth.gas_price),
    )
    signer1_balance = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    assert signer1_balance == signer1_balance_bf - transfer_amt
    signer1_balance_bf = signer1_balance

    receiver_balance = await ERC20.fns.balanceOf(receiver).call(w3, to=tf_erc20_addr)
    assert receiver_balance == receiver_balance_bf + transfer_amt
    receiver_balance_bf = receiver_balance

    # signer1 approve 2tf_erc20 to signer2
    approve_amt = 2
    assert signer1_balance_bf >= approve_amt

    res = await retry_on_nonce_mismatch(
        ERC20.fns.approve(signer2, approve_amt).transact,
        w3,
        signer1,
        to=tf_erc20_addr,
        gasPrice=await w3.eth.gas_price,
    )
    assert_approval_log(res, signer1, signer2, approve_amt)
    await asyncio.sleep(0.5)

    allowance = await ERC20.fns.allowance(signer1, signer2).call(w3, to=tf_erc20_addr)
    assert allowance == approve_amt

    approve_amt1 = 1
    res = await retry_on_nonce_mismatch(
        ERC20.fns.transferFrom(signer1, receiver, approve_amt1).transact,
        w3,
        signer2,
        to=tf_erc20_addr,
        gasPrice=await w3.eth.gas_price,
    )
    transfer_logs = [
        log
        for log in res["logs"]
        if log["topics"][0] == HexBytes(ERC20.events.Transfer.topic.hex())
    ]
    assert len(transfer_logs) == 1
    assert_approval_log(res, signer1, signer2, approve_amt - approve_amt1)

    signer1_balance = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    assert signer1_balance == signer1_balance_bf - approve_amt1
    signer1_balance_bf = signer1_balance

    signer2_balance = await ERC20.fns.balanceOf(signer2).call(w3, to=tf_erc20_addr)
    assert signer2_balance == signer2_balance_bf
    receiver_balance = await ERC20.fns.balanceOf(receiver).call(w3, to=tf_erc20_addr)
    assert receiver_balance == receiver_balance_bf + approve_amt1
    receiver_balance_bf = receiver_balance


def edit_app_cfg(cli, i, app_config={}):
    # Modify the json-rpc addresses to avoid conflict
    cluster.edit_app_cfg(
        cli.home(i) / "config/app.toml",
        cli.base_port(i),
        jsonmerge.merge(
            {
                "json-rpc": {
                    "enable": True,
                    "address": "127.0.0.1:{EVMRPC_PORT}",
                    "ws-address": "127.0.0.1:{EVMRPC_PORT_WS}",
                },
            },
            app_config,
        ),
    )


def duration(duration_str):
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    parts = re.findall(r"(\d+)([smhd])", duration_str.lower())
    return sum(int(value) * mult[unit] for value, unit in parts)


def wait_for_balance_change(cli, addr, denom, init_balance):
    def check_balance():
        current_balance = cli.balance(addr, denom)
        return current_balance if current_balance != init_balance else None

    return wait_for_fn("balance change", check_balance)


async def deploy_wom(w3: AsyncWeb3, account: BaseAccount) -> str:
    artifact = build_contract("WOM")
    await ensure_create2_deployed(w3, account)
    return await ensure_deployed_by_create2(
        w3,
        account,
        get_initcode(artifact),
        salt=WETH_SALT,
    )


async def w3_wait_for_new_blocks_async(w3: AsyncWeb3, n: int, sleep=0.1):
    begin_height = await w3.eth.block_number
    target = begin_height + n

    while True:
        cur_height = await w3.eth.block_number
        if cur_height >= target:
            break
        await asyncio.sleep(sleep)


def update_node_cmd(path, cmd, i, **kwargs):
    ini_path = path / cluster.SUPERVISOR_CONFIG_FILE
    ini = configparser.RawConfigParser()
    ini.read(ini_path)
    for section in ini.sections():
        if section == f"program:{CHAIN_ID}-node{i}":
            updates = {}
            base_cmd = f"{cmd} start --home %(here)s/node{i}"
            if kwargs:
                extra_flags = " ".join(
                    f"--{k.replace('_', '-')}" for k in kwargs.keys()
                )
                updates["command"] = f"{base_cmd} {extra_flags}"
            else:
                updates["command"] = base_cmd
            updates["autorestart"] = "false"
            ini[section].update(updates)
    with ini_path.open("w") as fp:
        ini.write(fp)


def grpc_eth_call(
    port: int,
    args: dict,
    expect_cb,
    chain_id=None,
    proposer_address=None,
):
    max_retry = 3
    sleep = 1
    success = False
    for i in range(max_retry):
        params = {
            "args": base64.b64encode(json.dumps(args).encode()).decode(),
        }
        if chain_id is not None:
            params["chain_id"] = str(chain_id)
        if proposer_address is not None:
            params["proposer_address"] = str(proposer_address)
        rsp = requests.get(
            f"http://localhost:{port}/cosmos/evm/vm/v1/eth_call", params
        ).json()
        success = expect_cb(rsp)
        if success:
            break
        time.sleep(sleep)
    assert success, str(rsp)


def verify_tax_distribution(cli, height, denom=DEFAULT_DENOM, scale_factor=1):
    tax_params = cli.get_params("tax")
    mca_tax = float(tax_params.get("mca_tax", "0")) / 1e18
    if mca_tax == 0:
        return None

    mca_addr = tax_params["mca_address"]
    modules = ["distribution", "fee_collector", "precisebank"]
    addrs = [module_address(m) for m in modules]
    height_bf = height - 1
    denom_af = DEFAULT_DENOM if scale_factor > 1 else denom

    balances_bf = {
        name: cli.balance(addr, denom=denom, height=height_bf)
        for name, addr in zip(modules, addrs)
    }
    balances_bf["mca"] = cli.balance(mca_addr, denom=denom, height=height_bf)

    balances_af = {
        name: cli.balance(addr, denom=denom_af, height=height)
        for name, addr in zip(modules, addrs)
    }
    balances_af["mca"] = cli.balance(mca_addr, denom=denom_af, height=height)
    assert balances_af["fee_collector"] == balances_af["precisebank"] == 0

    fee_collector = addrs[1]
    fee_frac = cli.query_precisebank_fraction(fee_collector, height=height_bf)

    rsp = requests.get(f"{cli.node_rpc_http}/block_results?height={height}").json()
    block_mint = int(
        find_log_event_attrs(
            rsp["result"]["finalize_block_events"], "mint", lambda a: "amount" in a
        )["amount"]
    )
    print(f"block_mint: {block_mint}, tax: {mca_tax}, fee_frac: {fee_frac} in {height}")

    # verify tax split
    precision = 10**18
    expected = {}
    for k in ["mca", "distribution"]:
        tax_rate_int = int(mca_tax * precision)
        if k == "mca":
            rate = tax_rate_int
        else:
            rate = precision - tax_rate_int

        exp = (block_mint * rate) // precision
        # add fee_collector fractional: (frac * 4 * rate) / precision
        if fee_frac > 0 and scale_factor > 1:
            fee_frac_scaled = fee_frac * 4
            frac_portion = (fee_frac_scaled * rate) // precision
            exp += frac_portion

        expected[k] = exp

    tolerance = 1
    increases = {
        k: balances_af[k] - balances_bf[k] * scale_factor
        for k in ["mca", "distribution"]
    }
    fee_inc = balances_af["fee_collector"] - balances_bf["fee_collector"] * scale_factor
    assert fee_inc == 0
    for mod, inc in increases.items():
        diff = abs(inc - expected[mod])
        assert diff <= tolerance, f"{mod} diff {diff}: exp={expected[mod]}, got={inc}"
        msg = f"module {mod}: {inc}"
        if scale_factor > 1:
            fractional = inc - expected[mod]
            msg += f" (mint={expected[mod]}+frac~{fractional})"
        else:
            msg += f" (exp={expected[mod]}, ±{diff})"
        print(msg)


def assert_withdraw_rewards(mantra, cb, denom=DEFAULT_DENOM, scale=1, **kwargs):
    cli = mantra.cosmos_cli()
    val = cli.address("validator", "val")
    validator = cli.address("validator")
    signer1 = cli.address("signer1")
    signer2 = cli.address("signer2")
    amt = 20_000_000
    coin = f"{amt}{denom}"

    rsp = cli.set_withdraw_addr(signer2, from_=signer1, **kwargs)
    assert rsp["code"] == 0, rsp["raw_log"]
    rsp = cli.delegate_amount(val, coin, _from=signer1, **kwargs)
    assert rsp["code"] == 0, rsp["raw_log"]
    rsp = cli.delegate_amount(val, coin, _from=validator, **kwargs)
    assert rsp["code"] == 0, rsp["raw_log"]

    cli, target_height = cb(cli)
    rewards = [
        cli.distribution_rewards(signer1, height=target_height - 1),
        cli.distribution_rewards(signer1, height=target_height),
    ]
    diff = rewards[1] / (rewards[0] * scale)
    assert diff > 0.99 and diff < 2, "rewards should increase"

    height_bf = cli.block_height()
    rsp = cli.withdraw_rewards(val, from_=signer1)
    assert rsp["code"] == 0, rsp["raw_log"]
    height_af = int(rsp["height"])
    balances = [
        cli.balance(signer2, height=height_af - 1),
        cli.balance(signer2, height=height_af),
    ]
    mantra.supervisorctl("stop", "mantra-canary-net-1-node0")

    def get_reward_ratio(height):
        dis = cli.export(
            modules_to_export="distribution",
            height=height,
        )[
            "app_state"
        ]["distribution"]
        data = dis["delegator_starting_infos"]
        info = [
            r
            for r in data
            if r["validator_address"] == val and r["delegator_address"] == signer1
        ][0]["starting_info"]
        period = info["previous_period"]
        stake = float(info["stake"]) / scale
        data = dis["validator_historical_rewards"]
        rewards = [
            r for r in data if r["validator_address"] == val and r["period"] == period
        ]
        assert len(rewards) == 1, rewards
        return stake, float(
            rewards[0]["rewards"]["cumulative_reward_ratio"][0]["amount"]
        )

    _, start = get_reward_ratio(height_bf)
    stake, end = get_reward_ratio(height_af)
    assert int(stake * (end - start)) == int((balances[1] - balances[0]) / scale)
    return target_height


def create_consumer_chain(
    cli,
    chain_id,
    dummy_hash="2D5C2110941DA54BE07CBB9FACD7E4A2E3253E79BE7BE3E5A1A7BDA518BAA4BE",
    **kwargs,
):
    spawn_time = datetime.datetime.now(datetime.UTC)
    top_n = 0
    consumer_msg = {
        "chain_id": chain_id,
        "metadata": {
            "name": "name",
            "description": "description",
            "metadata": "metadata",
        },
        "initialization_parameters": {
            "initial_height": {"revision_number": 1, "revision_height": 1},
            "genesis_hash": dummy_hash,
            "binary_hash": dummy_hash,
            "spawn_time": spawn_time.isoformat().replace("+00:00", "Z"),
            "ccv_timeout_period": 2419200000000000,
            "unbonding_period": 80000000000,
            "transfer_timeout_period": 60000000000,
            "consumer_redistribution_fraction": "0.75",
            "blocks_per_distribution_transmission": 10,
            "historical_entries": 1000,
            "distribution_transmission_channel": "",
        },
        "power_shaping_parameters": {"top_N": top_n},
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(consumer_msg, f)
        msg_path = Path(f.name)

    rsp = cli.provider_create_consumer(msg_path, **kwargs)
    assert rsp["code"] == 0, rsp["raw_log"]
    data = find_log_event_attrs(
        rsp["events"], "create_consumer", lambda attrs: "consumer_id" in attrs
    )
    consumer_id = data["consumer_id"]
    assert consumer_id is not None
    return consumer_id


def update_consumer_chain(
    cli,
    consumer_id,
    path,
    owner_address,
    new_owner_address,
    allowlisted_reward_denoms=None,
    **kwargs,
):
    dummy_hash = "2D5C2110941DA54BE07CBB9FACD7E4A2E3253E79BE7BE3E5A1A7BDA518BAA4BE"
    spawn_time = datetime.datetime.now(datetime.UTC)
    update_msg = {
        "consumer_id": consumer_id,
        "owner_address": owner_address,
        "new_owner_address": new_owner_address,
        "metadata": {
            "name": "name",
            "description": "description",
            "metadata": "metadata",
        },
        "initialization_parameters": {
            "initial_height": {"revision_number": 1, "revision_height": 1},
            "genesis_hash": dummy_hash,
            "binary_hash": dummy_hash,
            "spawn_time": spawn_time.isoformat().replace("+00:00", "Z"),
            "ccv_timeout_period": 2419200000000000,
            "unbonding_period": 80000000000,
            "transfer_timeout_period": 60000000000,
            "consumer_redistribution_fraction": "0.75",
            "blocks_per_distribution_transmission": 10,
            "historical_entries": 1000,
            "distribution_transmission_channel": "",
        },
        "power_shaping_parameters": {
            "top_N": 0,
            "validators_power_cap": 0,
            "validator_set_cap": 50,
            "allowlist": [],
            "denylist": [],
            "min_stake": 1000,
            "allow_inactive_vals": True,
            "prioritylist": [],
        },
    }

    if allowlisted_reward_denoms is not None:
        update_msg["allowlisted_reward_denoms"] = allowlisted_reward_denoms

    msg_path = path / "update_consumer_msg.json"
    msg_path.write_text(json.dumps(update_msg))
    rsp = cli.provider_update_consumer(msg_path, **kwargs)
    assert rsp["code"] == 0, f"Failed to update consumer: {rsp.get('raw_log', '')}"
    return rsp

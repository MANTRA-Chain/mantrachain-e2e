import asyncio
import hashlib
import json
import os
import pathlib
import sys
import time
from typing import Any

from eth_account import Account
from web3 import AsyncWeb3
from web3.middleware import ExtraDataToPOAMiddleware

# make the integration_tests package importable regardless of CWD
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from integration_tests.doc_utils import (  # noqa: E402
    DOCUMENT_ADDRESS,
    DOCUMENT_PRECOMPILE,
)

RPC_URL = os.getenv("EVM_RPC", "https://evm.testnet.nvnmchain.io")
CHAIN_ID = int(os.getenv("EVM_CHAIN_ID", "787111"))
GAS_MULTIPLIER = float(os.getenv("GAS_MULTIPLIER", "1.5"))
EXTRA_GAS = int(os.getenv("EXTRA_GAS", "50000"))

Account.enable_unaudited_hdwallet_features()


def _load_account() -> Account:
    pk = os.getenv("PRIVATE_KEY")
    if pk:
        return Account.from_key(pk)
    mnemonic = os.getenv("MNEMONIC")
    if mnemonic:
        return Account.from_mnemonic(mnemonic)
    print(
        "ERROR: set PRIVATE_KEY or MNEMONIC env var.",
        file=sys.stderr,
    )
    sys.exit(1)



def intrinsic_calldata_gas(data: bytes | str) -> int:
    """21 000 base + 4 per zero byte + 16 per non-zero byte."""
    if isinstance(data, str):
        raw = data[2:] if data.startswith("0x") else data
        data = bytes.fromhex(raw)
    else:
        data = bytes(data)
    cost = 21_000
    for b in data:
        cost += 4 if b == 0 else 16
    return cost


async def estimate_gas(w3: AsyncWeb3, *, sender: str, data) -> int:
    return int(
        await w3.eth.estimate_gas(
            {
                "to": DOCUMENT_ADDRESS,
                "from": sender,
                "data": data,
            }
        )
    )


async def build_tx_params(
    w3: AsyncWeb3,
    *,
    sender: str,
    data,
    gas_override: int | None = None,
) -> dict:
    """Return fee + gas params for a precompile call.

    If *gas_override* is set that value is used directly (no estimate).
    Otherwise eth_estimateGas is called and the result is scaled by
    GAS_MULTIPLIER + EXTRA_GAS.
    """
    estimated: int | None = None

    if gas_override is not None:
        gas_limit = gas_override
    else:
        try:
            estimated = await estimate_gas(w3, sender=sender, data=data)
            gas_limit = int(estimated * GAS_MULTIPLIER) + EXTRA_GAS
        except Exception as exc:
            print(f"  [warn] eth_estimateGas failed ({exc}); falling back to block gas limit")
            gas_limit = None  # resolved below from block

    # EIP-1559 preferred – also resolves block-gas-limit fallback in one fetch
    try:
        block = await w3.eth.get_block("latest")
        block_gas_limit = int(block.get("gasLimit", 40_000_000))
        if gas_limit is None:
            # no estimate available: use the full block gas limit so the tx
            # cannot be killed by a too-tight cap
            gas_limit = block_gas_limit
            print(f"  [info] using block gas limit as cap: {gas_limit}")
        base_fee = block.get("baseFeePerGas")
        if base_fee is not None:
            base_fee = int(base_fee)
            priority_fee = 2_000_000_000  # 2 gwei
            return {
                "gas": gas_limit,
                "maxFeePerGas": base_fee * 2 + priority_fee,
                "maxPriorityFeePerGas": priority_fee,
                "_estimated": estimated,
            }
    except Exception:
        pass

    # legacy fallback
    try:
        price = int(await w3.eth.gas_price)
        return {"gas": gas_limit, "gasPrice": price, "_estimated": estimated}
    except Exception:
        return {"gas": gas_limit, "_estimated": estimated}



async def send_precompile_call(
    w3: AsyncWeb3,
    account: Account,
    call,
    *,
    label: str,
    gas_override: int | None = None,
) -> dict[str, Any]:
    """Send a precompile call, wait for the receipt, and return a stats dict."""
    data = call.data

    txp = await build_tx_params(w3, sender=account.address, data=data, gas_override=gas_override)
    estimated = txp.pop("_estimated", None)

    nonce = await w3.eth.get_transaction_count(account.address, "pending")
    raw_tx = {
        "to": DOCUMENT_ADDRESS,
        "from": account.address,
        "data": data,
        "nonce": nonce,
        "chainId": CHAIN_ID,
        **txp,
    }

    signed = account.sign_transaction(raw_tx)
    tx_hash = await w3.eth.send_raw_transaction(signed.raw_transaction)

    print(f"  sent  txhash={tx_hash.hex()}")
    receipt = await w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    intrinsic = intrinsic_calldata_gas(data)
    gas_used = int(receipt["gasUsed"])
    exec_delta = gas_used - intrinsic  # execution cost above the calldata cost

    stats = {
        "label": label,
        "status": "OK" if receipt.status == 1 else "FAIL",
        "tx_hash": tx_hash.hex(),
        "gas_limit": txp.get("gas"),
        "estimated": estimated,
        "gas_used": gas_used,
        "intrinsic": intrinsic,
        "exec_delta": exec_delta,
    }
    return stats



async def get_registry_id(w3: AsyncWeb3, name: str) -> int:
    registries, _ = await DOCUMENT_PRECOMPILE.fns.registries(
        0, name, (b"", 0, 10, False, False)
    ).call(w3, to=DOCUMENT_ADDRESS)
    reg = next((r for r in registries if r[1] == name), None)
    if reg is None:
        raise RuntimeError(f"registry '{name}' not found after creation")
    return int(reg[0])


async def get_record(w3: AsyncWeb3, registry: str, checksum: str):
    records, _ = await DOCUMENT_PRECOMPILE.fns.records(
        registry, checksum, 0, 0, (b"", 0, 50, False, False)
    ).call(w3, to=DOCUMENT_ADDRESS)
    if not records:
        raise RuntimeError(f"no records found for registry={registry} checksum={checksum}")
    return max(records, key=lambda r: int(r[8]))  # highest index



async def run_tests(w3: AsyncWeb3, account: Account) -> list[dict]:
    stats_list: list[dict] = []

    tag = int(time.time())
    registry_name = f"nvnm-manual-{tag}"
    checksum = hashlib.sha256(f"manual-record-{tag}".encode()).hexdigest()

    print(f"\n[1/5] addRegistry  name={registry_name}")
    call = DOCUMENT_PRECOMPILE.fns.addRegistry(
        registry_name,
        "manual smoke-test registry",
        json.dumps({"source": "manual-test", "ts": tag}),
    )
    stats = await send_precompile_call(w3, account, call, label="addRegistry")
    stats_list.append(stats)
    _print_stats(stats)

    if stats["status"] != "OK":
        print("  ABORT: addRegistry failed – cannot continue")
        return stats_list

    registry_id = await get_registry_id(w3, registry_name)
    print(f"  registry_id={registry_id}")

    print(f"\n[2/5] addRecord  checksum={checksum[:16]}...")
    record_tuple = (
        registry_name,              # registry
        f"ipfs://{checksum}",       # uri
        checksum,                   # checksum
        "sha256",                   # checksumAlgo
        json.dumps({"name": "manual-record", "ts": tag}),  # metadata
        "",                         # timestamp (chain fills it)
        "active",                   # status
        0,                          # recordId (assigned by chain)
        0,                          # index
        False,                      # isLatest
    )
    call = DOCUMENT_PRECOMPILE.fns.addRecord(record_tuple)
    stats = await send_precompile_call(w3, account, call, label="addRecord")
    stats_list.append(stats)
    _print_stats(stats)

    if stats["status"] != "OK":
        print("  ABORT: addRecord failed – skipping dependent steps")
        return stats_list

    record = await get_record(w3, registry_name, checksum)
    record_id = int(record[7])
    record_index = int(record[8])
    print(f"  record_id={record_id}  index={record_index}")

    print(f"\n[3/5] updateRecordStatus  record_id={record_id}  -> 'verified'")
    call = DOCUMENT_PRECOMPILE.fns.updateRecordStatus(
        registry_id,
        record_id,
        record_index,
        "verified",
    )
    stats = await send_precompile_call(w3, account, call, label="updateRecordStatus")
    stats_list.append(stats)
    _print_stats(stats)

    print(f"\n[4/5] grantRole  registry_id={registry_id}  role=editor")
    # grant role on the record checksum to the sender themselves (safe no-op target)
    call = DOCUMENT_PRECOMPILE.fns.grantRole(
        registry_id,
        checksum,
        account.address,
        "editor",
    )
    stats = await send_precompile_call(w3, account, call, label="grantRole")
    stats_list.append(stats)
    _print_stats(stats)

    print(f"\n[5/5] revokeRole  registry_id={registry_id}  role=editor")
    call = DOCUMENT_PRECOMPILE.fns.revokeRole(
        registry_id,
        checksum,
        account.address,
        "editor",
    )
    stats = await send_precompile_call(w3, account, call, label="revokeRole")
    stats_list.append(stats)
    _print_stats(stats)

    return stats_list


def _print_stats(s: dict) -> None:
    est_str = str(s["estimated"]) if s["estimated"] is not None else "n/a"
    over_str = (
        f"{s['gas_used'] / s['gas_limit'] * 100:.1f}%"
        if s["gas_limit"]
        else "n/a"
    )
    print(
        f"  status={s['status']}"
        f"  limit={s['gas_limit']}"
        f"  estimated={est_str}"
        f"  used={s['gas_used']}"
        f"  intrinsic={s['intrinsic']}"
        f"  exec_delta={s['exec_delta']}"
        f"  utilisation={over_str}"
    )


def _print_summary(stats_list: list[dict]) -> None:
    print("\n" + "=" * 90)
    print(f"{'Method':<22} {'Status':>6} {'Limit':>9} {'Estimated':>10} {'Used':>8} {'Intrinsic':>10} {'ExecΔ':>8} {'Util%':>6}")
    print("-" * 90)
    for s in stats_list:
        est_str = str(s["estimated"]) if s["estimated"] is not None else "n/a"
        util = (
            f"{s['gas_used'] / s['gas_limit'] * 100:.1f}"
            if s["gas_limit"]
            else "n/a"
        )
        print(
            f"{s['label']:<22} {s['status']:>6} {s['gas_limit']:>9} {est_str:>10}"
            f" {s['gas_used']:>8} {s['intrinsic']:>10} {s['exec_delta']:>8} {util:>6}"
        )
    print("=" * 90)
    failed = [s for s in stats_list if s["status"] != "OK"]
    if failed:
        print(f"\nFAILED ({len(failed)}): {[s['label'] for s in failed]}")
    else:
        print("\nAll calls succeeded.")



async def main() -> None:
    account = _load_account()

    print(f"RPC          : {RPC_URL}")
    print(f"Chain ID     : {CHAIN_ID}")
    print(f"Sender       : {account.address}")
    print(f"Gas multiplier: {GAS_MULTIPLIER}x  +{EXTRA_GAS} flat extra")
    print(f"Precompile   : {DOCUMENT_ADDRESS}")

    w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(RPC_URL))
    # Some EVM-compatible chains return extra fields in block headers;
    # this middleware swallows the ExtraData validation error.
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    # Sanity-check connectivity
    block_num = await w3.eth.block_number
    balance = await w3.eth.get_balance(account.address)
    print(f"Block        : {block_num}")
    print(f"Balance      : {balance} wei")
    if balance == 0:
        print("WARNING: sender balance is zero – transactions will fail")

    stats_list = await run_tests(w3, account)
    _print_summary(stats_list)

    any_failed = any(s["status"] != "OK" for s in stats_list)
    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    asyncio.run(main())

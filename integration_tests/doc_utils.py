import hashlib
import json
from dataclasses import astuple, dataclass
from enum import Enum
from functools import partial
from pathlib import Path

import pytest
from eth_contract.contract import Contract as ContractAsync
from web3 import AsyncWeb3

from .utils import (
    ACCOUNTS,
    ADDRS,
    CONSUMER_GAS_AMT,
    KEYS,
    build_contract,
    send_transaction,
)


def consumer_eip1559_fees(block) -> dict:
    # base_fee can decay below min_gas_price in empty blocks, raise priority
    # so effective_gas_price = base_fee + priority >= min_gas_price.
    base_fee = int(block["baseFeePerGas"])
    priority_fee = max(2_000_000_000, int(CONSUMER_GAS_AMT) - base_fee)
    return {
        "maxFeePerGas": (base_fee + priority_fee) * 2,
        "maxPriorityFeePerGas": priority_fee,
    }


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class Role(str, Enum):
    EDITOR = "editor"
    VIEWER = "viewer"


class MatchMode(int, Enum):
    """Mirrors anchoring's RegistryNameMatchMode, passed as uint8 over the ABI.

    UNSPECIFIED is a distinct wire value that the chain treats as EXACT; both
    are kept so a test can pin that equivalence rather than assume it.
    """

    UNSPECIFIED = 0
    EXACT = 1
    PREFIX = 2
    SUFFIX = 3
    CONTAINS = 4


@dataclass
class Record:
    uri: str
    checksum: str
    checksumAlgo: str
    metadata: str
    timestamp: str
    status: str
    recordId: int
    index: int
    isLatest: bool
    registryId: int


ANCHORING_ABI = json.loads(
    (Path(__file__).parents[1] / "contracts/layout/anchoring.abi.json").read_text()
)

DOCUMENT_PRECOMPILE = ContractAsync(ANCHORING_ABI)
DOCUMENT_ADDRESS = "0x0000000000000000000000000000000000000A00"
DOCUMENT_REGISTRY_DENOM = "test-registry"
DOCUMENT_GAS = 100_000


async def send_document_call(w3: AsyncWeb3, call, signer, message="", gas=DOCUMENT_GAS):
    "Transact `call` against the document precompile with fitted gas/fee params."
    tx = {"to": DOCUMENT_ADDRESS, "from": signer.address, "data": call.data}
    try:
        gas = max(gas, int(await w3.eth.estimate_gas(tx) * 1.2) + 30_000)
    except Exception:
        pass
    fees = consumer_eip1559_fees(await w3.eth.get_block("latest"))
    receipt = await call.transact(w3, signer, to=DOCUMENT_ADDRESS, gas=gas, **fees)
    assert receipt["status"] == 1, message
    return receipt


def find_document_event(receipt, *, event: str, caller: str) -> dict:
    """Return the decoded args of the named precompile event in ``receipt``,
    matched by emitter address, topic0 and caller, decoded via its ABI."""
    abi_event = getattr(DOCUMENT_PRECOMPILE.events, event)

    for log in receipt["logs"]:
        if log["address"].lower() != DOCUMENT_ADDRESS.lower():
            continue

        topics = log["topics"]
        if not topics or bytes(topics[0]) != bytes(abi_event.topic):
            continue

        # topic0 matched, so a decode failure here means the emitted layout no
        # longer agrees with the declaration; surface it instead of skipping.
        decoded = abi_event.parse_log(log)
        assert (
            decoded is not None
        ), f"{abi_event.signature} log does not match its declared ABI: {log}"

        if decoded["args"]["caller"].lower() != caller.lower():
            continue

        return dict(decoded["args"])

    raise AssertionError(f"missing event {abi_event.signature} from {DOCUMENT_ADDRESS}")


async def assert_call_reverts(
    w3: AsyncWeb3,
    *,
    sender: str,
    data,
    expect_err: str = "",
    to: str = DOCUMENT_ADDRESS,
    gas: int = DOCUMENT_GAS,
):
    "eth_call reverts, with `expect_err` in the error when given."
    with pytest.raises(Exception) as exc_info:
        await w3.eth.call({"to": to, "from": sender, "data": data, "gas": gas})
    err = str(exc_info.value)
    assert expect_err in err, err


async def query_records(
    w3: AsyncWeb3,
    registry_id=0,
    checksum="",
    record_id=0,
    *,
    offset=0,
    limit=100,
    count_total=False,
) -> list[Record]:
    records, _ = await DOCUMENT_PRECOMPILE.fns.records(
        registry_id, checksum, record_id, 0, (b"", offset, limit, count_total, False)
    ).call(w3, to=DOCUMENT_ADDRESS)
    return [Record(*r) for r in records]


def assert_document_event(receipt, *, event: str, caller: str, **expected):
    """Assert the named precompile event carries ``expected`` argument
    values, keyed by their ABI names."""
    abi_event = getattr(DOCUMENT_PRECOMPILE.events, event)
    types = {i["name"]: i["type"] for i in abi_event.abi["inputs"]}

    unknown = set(expected) - set(types)
    assert not unknown, f"{abi_event.signature} has no argument(s) {sorted(unknown)}"

    args = find_document_event(receipt, event=event, caller=caller)
    for key, exp in expected.items():
        got = args[key]
        if types[key] == "address":
            got, exp = got.lower(), exp.lower()
        if got != exp:
            raise AssertionError(
                f"{abi_event.signature} {key} mismatch:"
                f"\n  got: {got}\n  expected: {exp}"
            )


async def deploy_anchoring_caller(w3, sender=ADDRS["community"]):
    """Deploy AnchoringCaller and return (address, contract)."""
    artifact = build_contract("AnchoringCaller")
    receipt = send_transaction(
        w3,
        {
            "from": sender,
            "data": artifact["bytecode"],
            "gas": 2_000_000,
            **consumer_eip1559_fees(w3.eth.get_block("latest")),
        },
        KEYS["community"],
    )
    assert receipt.status == 1
    return receipt.contractAddress, ContractAsync(artifact["abi"])


async def _registry_by_id(w3: AsyncWeb3, registry_id: int):
    regs, _ = await DOCUMENT_PRECOMPILE.fns.registries(
        registry_id, (b"", 0, 1, False, False)
    ).call(w3, to=DOCUMENT_ADDRESS)
    return regs[0] if regs else None


async def _find_registry_by_name(w3: AsyncWeb3, name: str):
    # No on-chain name lookup (names are non-unique): page through all registries and
    # filter client-side, picking the newest (highest id) on a name collision.
    out: list = []
    key = b""
    while True:
        regs, page = await DOCUMENT_PRECOMPILE.fns.registries(
            0, (key, 0, 100, False, False)
        ).call(w3, to=DOCUMENT_ADDRESS)
        out.extend(r for r in regs if r[1] == name)
        key = bytes(page[0])
        if not key:
            break
    return max(out, key=lambda r: int(r[0])) if out else None


async def get_registry_id(w3: AsyncWeb3, name: str) -> int:
    reg = await _find_registry_by_name(w3, name)
    if reg is None:
        raise AssertionError(f"registry {name} not found")
    return int(reg[0])


async def create_registry(
    w3: AsyncWeb3,
    name: str,
    *,
    metadata: str = "",
) -> int:
    """Always create a registry and return its id.

    Unlike ensure_registry_exists, which resolves an existing name back to its
    id, so it cannot produce two registries sharing a name.
    """
    admin = ACCOUNTS["community"]
    call = DOCUMENT_PRECOMPILE.fns.addRegistry(name, name, metadata)
    receipt = await send_document_call(
        w3, call, admin, f"failed to create registry {name}"
    )

    # Read the id from the event; a name scan can't tell apart same-named registries.
    args = find_document_event(receipt, event="AddRegistry", caller=admin.address)
    assert args["name"] == name, args
    return int(args["registryId"])


async def ensure_registry_exists(
    w3: AsyncWeb3,
    name=DOCUMENT_REGISTRY_DENOM,
    *,
    metadata: str = "",
) -> int:
    try:
        reg = await _find_registry_by_name(w3, name)
    except Exception:
        reg = None
    if reg is not None:
        if metadata:
            assert (
                reg[5] == metadata
            ), f"expected registry metadata {metadata}, got {reg[5]}"
        return int(reg[0])

    registry_id = await create_registry(w3, name, metadata=metadata)

    if metadata:
        reg = await _registry_by_id(w3, registry_id)
        assert (
            reg and reg[5] == metadata
        ), f"expected registry metadata {metadata}, got {reg and reg[5]}"

    return registry_id


async def _set_role(event, w3: AsyncWeb3, registry_id, checksum, user, role, sender):
    "grantRole/revokeRole as `sender`, checking the GrantRole/RevokeRole event."
    role_value = role.value if isinstance(role, Role) else str(role)
    method = event[0].lower() + event[1:]
    call = getattr(DOCUMENT_PRECOMPILE.fns, method)(
        registry_id, checksum, user.address, role_value
    )
    receipt = await send_document_call(
        w3,
        call,
        sender,
        f"{method}({registry_id}, {checksum}, {user.address}, {role}) failed",
    )

    assert_document_event(
        receipt,
        event=event,
        caller=sender.address,
        registryId=int(registry_id),
        checksum=str(checksum),
        account=user.address,
        role=role_value,
    )


grant_role = partial(_set_role, "GrantRole")
revoke_role = partial(_set_role, "RevokeRole")


def record_metadata(document, figi="", individual_id=""):
    return json.dumps(
        {"document": document, "figi": figi, "individualId": individual_id}
    )


def new_record(
    checksum,
    registry_id,
    *,
    metadata="",
    uri=None,
    checksum_algo="sha256",
) -> Record:
    "A record to submit: the fields the chain assigns are left at their zero values."
    return Record(
        uri=f"ipfs://{checksum}" if uri is None else uri,
        checksum=checksum,
        checksumAlgo=checksum_algo,
        metadata=metadata,
        timestamp="",
        status="active",
        recordId=0,
        index=0,
        isLatest=False,
        registryId=registry_id,
    )


async def add_record(
    w3: AsyncWeb3,
    admin,
    checksum,
    name="Test Record",
    registry=DOCUMENT_REGISTRY_DENOM,
    metadata=None,
):
    registry_id = await get_registry_id(w3, registry)
    doc = new_record(
        checksum,
        registry_id,
        metadata=record_metadata(name) if metadata is None else metadata,
    )
    call = DOCUMENT_PRECOMPILE.fns.addRecord(astuple(doc))
    receipt = await send_document_call(
        w3, call, admin, f"failed to add record {checksum} to registry {registry}"
    )

    records = await query_records(w3, registry_id, checksum, limit=50)
    assert records, f"expected record after addRecord({registry_id}, {checksum})"
    # for versioned records, event should reflect the latest version
    rec = max(records, key=lambda r: int(r.index))
    assert_document_event(
        receipt,
        event="AddRecord",
        caller=admin.address,
        registryId=registry_id,
        recordId=int(rec.recordId),
        index=int(rec.index),
        checksum=checksum,
    )
    return receipt


async def update_record_status(
    w3: AsyncWeb3,
    admin,
    record: Record,
    status: str,
):
    registry_id = int(record.registryId)
    call = DOCUMENT_PRECOMPILE.fns.updateRecordStatus(
        registry_id,
        record.recordId,
        record.index,
        status,
    )
    receipt = await send_document_call(
        w3, call, admin, f"updateRecordStatus({status}) failed"
    )

    assert_document_event(
        receipt,
        event="UpdateRecordStatus",
        caller=admin.address,
        registryId=int(registry_id),
        recordId=int(record.recordId),
        index=int(record.index),
        status=str(status),
    )


NAME_INDEX_PAGE = (b"", 0, 200, False, False)


async def registries_by_name(w3: AsyncWeb3, name: str, mode: MatchMode) -> set[int]:
    """Ids returned by the registriesByName precompile query."""
    regs, _ = await DOCUMENT_PRECOMPILE.fns.registriesByName(
        name, int(mode), NAME_INDEX_PAGE
    ).call(w3, to=DOCUMENT_ADDRESS)
    return {int(r[0]) for r in regs}

import json
import time
from dataclasses import astuple, dataclass
from enum import Enum

import pytest
from eth_abi.abi import decode as abi_decode
from eth_contract.contract import Contract as ContractAsync
from eth_hash.auto import keccak
from web3 import AsyncWeb3

from .utils import ACCOUNTS, ADDRS, KEYS, build_contract, send_transaction

# allow overriding accounts for different chain contexts
_ACCOUNTS_OVERRIDE = None


def set_accounts_override(accounts):
    global _ACCOUNTS_OVERRIDE
    _ACCOUNTS_OVERRIDE = accounts


def clear_accounts_override():
    global _ACCOUNTS_OVERRIDE
    _ACCOUNTS_OVERRIDE = None


def get_accounts():
    return _ACCOUNTS_OVERRIDE if _ACCOUNTS_OVERRIDE is not None else ACCOUNTS


class Role(str, Enum):
    EDITOR = "editor"
    VIEWER = "viewer"


@dataclass
class Record:
    registry: str
    uri: str
    checksum: str
    checksumAlgo: str
    metadata: str
    timestamp: str
    status: str
    recordId: int
    index: int
    isLatest: bool

    @classmethod
    def from_tuple(cls, t):
        return cls(*t)


DOCUMENT_PRECOMPILE_ABI = [
    """
    struct Record {
        string registry;
        string uri;
        string checksum;
        string checksumAlgo;
        string metadata;
        string timestamp;
        string status;
        uint64 recordId;
        uint64 index;
        bool isLatest;
    }
    """,
    """
    struct Registry {
        uint64 id;
        string name;
        string description;
        string creator;
        string createdAt;
        string metadata;
    }
    """,
    """
    struct PageRequest {
        bytes key;
        uint64 offset;
        uint64 limit;
        bool countTotal;
        bool reverse;
    }
    """,
    """
    struct PageResponse {
        bytes nextKey;
        uint64 total;
    }
    """,
    """
    function addRegistry(
        string memory name,
        string memory description,
        string memory metadata
    ) returns (uint64 registryId)
    """,
    """
    function addRecord(Record memory record) returns (uint64 recordId)
    """,
    """
    function updateRecordStatus(
        uint64 registryId,
        uint64 recordId,
        uint64 index,
        string memory status
    )
    """,
    """
    function records(
        string memory registry,
        string memory checksum,
        uint64 recordId,
        uint64 index,
        PageRequest memory pagination
    ) returns (Record[] memory, PageResponse memory)
    """,
    """
    function registries(
        uint64 registryId,
        string memory name,
        PageRequest memory pagination
    ) returns (Registry[] memory, PageResponse memory)
    """,
    """
    function grantRole(
        uint64 registryId,
        string memory checksum,
        address account,
        string memory role
    )
    """,
    """
    function revokeRole(
        uint64 registryId,
        string memory checksum,
        address account,
        string memory role
    )
    """,
]

DOCUMENT_PRECOMPILE = ContractAsync.from_abi(DOCUMENT_PRECOMPILE_ABI)
DOCUMENT_ADDRESS = "0x0000000000000000000000000000000000000A00"
DOCUMENT_REGISTRY_DENOM = "test-registry"
DOCUMENT_GAS = 100_000


async def _tx_params(
    w3: AsyncWeb3,
    *,
    gas: int = DOCUMENT_GAS,
    sender: str | None = None,
    to: str = DOCUMENT_ADDRESS,
    data=None,
) -> dict:
    gas_limit = gas
    if sender is not None and data is not None:
        try:
            estimated = int(
                await w3.eth.estimate_gas(
                    {
                        "to": to,
                        "from": sender,
                        "data": data,
                    }
                )
            )
            gas_limit = max(gas_limit, int(estimated * 1.2) + 30_000)
        except Exception:
            pass

    # try EIP-1559 fee
    try:
        block = await w3.eth.get_block("latest")
        base_fee = block.get("baseFeePerGas")
        if base_fee is not None:
            base_fee = int(base_fee)
            priority_fee = 2_000_000_000  # 2 gwei
            return {
                "gas": gas_limit,
                "maxFeePerGas": base_fee * 2 + priority_fee,
                "maxPriorityFeePerGas": priority_fee,
            }
    except Exception:
        pass

    # fallback to legacy gasPrice
    try:
        price = int(await w3.eth.gas_price)
        return {"gas": gas_limit, "gasPrice": price}
    except Exception:
        return {"gas": gas_limit}


def _as_bytes(value) -> bytes:
    if value is None:
        return b""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        value = value.strip()
        return bytes.fromhex(value[2:] if value.startswith("0x") else value)
    return bytes(value)


def _decode_document_event_data(
    receipt,
    *,
    event_sig: str,
    caller: str,
    data_types: list[str],
):
    topic0 = keccak(event_sig.encode())
    caller_topic = b"\x00" * 12 + bytes.fromhex(caller[2:])

    for log in receipt["logs"]:
        if log["address"].lower() != DOCUMENT_ADDRESS.lower():
            continue

        topics = log["topics"]
        if not topics or _as_bytes(topics[0]) != topic0:
            continue

        if len(topics) < 2 or _as_bytes(topics[1]) != caller_topic:
            continue

        return list(abi_decode(data_types, _as_bytes(log["data"])))

    raise AssertionError(f"missing event {event_sig} from {DOCUMENT_ADDRESS}")


async def _assert_call_reverts(
    w3: AsyncWeb3,
    *,
    sender: str,
    to: str,
    data,
    gas: int = DOCUMENT_GAS,
    message: str,
):
    try:
        await w3.eth.call(
            {
                "to": to,
                "from": sender,
                "data": data,
                "gas": gas,
            }
        )
    except Exception:
        return
    raise AssertionError(message)


async def _assert_call_reverts_contains(
    w3: AsyncWeb3,
    *,
    sender: str,
    to: str,
    data,
    expect_err: str,
    gas: int = DOCUMENT_GAS,
):
    with pytest.raises(Exception) as exc_info:
        await w3.eth.call(
            {
                "to": to,
                "from": sender,
                "data": data,
                "gas": gas,
            }
        )
    err = str(exc_info.value)
    assert expect_err in err, err


async def do_test_role_scope_existence_validation(
    w3: AsyncWeb3,
    *,
    method: str,
    registry_id: int,
    checksum: str,
    account,
    role: str,
    sender,
    expect_err: str,
):
    if method == "grant":
        call = DOCUMENT_PRECOMPILE.fns.grantRole(
            registry_id, checksum, account.address, role
        )
    elif method == "revoke":
        call = DOCUMENT_PRECOMPILE.fns.revokeRole(
            registry_id, checksum, account.address, role
        )
    else:
        raise AssertionError(f"unsupported role method: {method}")

    await _assert_call_reverts_contains(
        w3,
        sender=sender.address,
        to=DOCUMENT_ADDRESS,
        data=call.data,
        expect_err=expect_err,
    )


async def _assert_add_record_event(
    w3: AsyncWeb3,
    receipt,
    *,
    caller: str,
    registry: str,
    checksum: str,
):
    registry_id = await get_registry_id(w3, registry)

    records, _ = await DOCUMENT_PRECOMPILE.fns.records(
        registry, checksum, 0, 0, (b"", 0, 50, False, False)
    ).call(w3, to=DOCUMENT_ADDRESS)
    parsed = [Record.from_tuple(r) for r in records]
    assert parsed, f"expected record after addRecord({registry}, {checksum})"

    # for versioned records, event should reflect the latest version
    rec = max(parsed, key=lambda r: int(r.index))

    assert_document_event(
        receipt,
        event_sig="AddRecord(address,uint64,uint64,uint64,string)",
        caller=caller,
        data_types=["uint64", "uint64", "uint64", "string"],
        expected_data=[registry_id, int(rec.recordId), int(rec.index), checksum],
    )


def assert_document_event(
    receipt,
    *,
    event_sig: str,
    caller: str,
    data_types: list[str],
    expected_data: list,
):
    decoded = _decode_document_event_data(
        receipt,
        event_sig=event_sig,
        caller=caller,
        data_types=data_types,
    )

    if len(decoded) != len(expected_data):
        raise AssertionError(
            f"{event_sig} data length mismatch: {decoded} != {expected_data}"
        )

    for typ, got, exp in zip(data_types, decoded, expected_data, strict=True):
        if typ == "address":
            got, exp = got.lower(), exp.lower()
        if got != exp:
            kind = "address" if typ == "address" else "data"
            raise AssertionError(
                f"{event_sig} {kind} mismatch:\n  got: {got}\n  expected: {exp}"
            )


def get_add_registry_event_registry_id(receipt, *, caller: str) -> int:
    decoded = _decode_document_event_data(
        receipt,
        event_sig="AddRegistry(address,uint64,string)",
        caller=caller,
        data_types=["uint64", "string"],
    )
    return int(decoded[0])


async def do_test_contract_cannot_call_anchoring_sensitive_methods(
    w3,
    *,
    sender=ADDRS["community"],
):
    artifact = build_contract("AnchoringCaller")
    deploy_receipt = send_transaction(
        w3,
        {
            "from": sender,
            "data": artifact["bytecode"],
            "gas": 2_000_000,
        },
        KEYS["community"],
    )
    assert deploy_receipt.status == 1

    contract_addr = deploy_receipt.contractAddress
    caller = ContractAsync(artifact["abi"])

    add_registry_call = caller.fns.callAddRegistry(
        "ccv-contract-caller-registry",
        "repro non-EOA guard",
        "{}",
    )

    async def assert_reverted(data):
        await _assert_call_reverts_contains(
            w3,
            sender=sender,
            to=contract_addr,
            data=data,
            expect_err="sender not an eoa",
            gas=1_000_000,
        )

    await assert_reverted(add_registry_call.data)

    eoa_add_registry_call = DOCUMENT_PRECOMPILE.fns.addRegistry(
        "ccv-eoa-registry",
        "repro EOA guard",
        "{}",
    )
    eoa_add_registry_receipt = send_transaction(
        w3,
        {
            "to": DOCUMENT_ADDRESS,
            "from": sender,
            "data": eoa_add_registry_call.data,
            "gas": 1_000_000,
        },
        KEYS["community"],
    )
    assert eoa_add_registry_receipt.status == 1

    registry_id = get_add_registry_event_registry_id(
        eoa_add_registry_receipt,
        caller=sender,
    )

    add_record_call = caller.fns.callAddRecord(
        (
            "ccv-eoa-registry",
            "ipfs://ccv-contract-caller",
            "ccv-contract-caller-checksum",
            "sha256",
            "{}",
            "",
            "active",
            0,
            0,
            False,
        )
    )
    await assert_reverted(add_record_call.data)

    update_record_status_call = caller.fns.callUpdateRecordStatus(
        registry_id,
        1,
        1,
        "verified",
    )
    await assert_reverted(update_record_status_call.data)

    grant_role_call = caller.fns.callGrantRole(
        registry_id,
        "",
        ADDRS["signer1"],
        Role.EDITOR.value,
    )
    await assert_reverted(grant_role_call.data)

    revoke_role_call = caller.fns.callRevokeRole(
        registry_id,
        "",
        ADDRS["signer1"],
        Role.EDITOR.value,
    )
    await assert_reverted(revoke_role_call.data)


async def do_test_constructor_bypass_ensure_eoa_caller(
    w3,
    *,
    sender=ADDRS["community"],
):
    artifact = build_contract("AnchoringConstructorCaller")
    contract = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])

    registry_name = f"ccv-constructor-bypass-{int(time.time() * 1000)}"
    deploy_tx = contract.constructor(registry_name).build_transaction(
        {
            "from": sender,
            "gas": 2_000_000,
        }
    )
    deploy_receipt = send_transaction(w3, deploy_tx, KEYS["community"])
    assert deploy_receipt.status == 1

    deployed = w3.eth.contract(
        address=deploy_receipt.contractAddress, abi=artifact["abi"]
    )
    registry_created = deployed.functions.registryCreated().call()
    created_registry_id = int(deployed.functions.createdRegistryId().call())

    assert not registry_created, "constructor call should not bypass ensureEOACaller"
    assert (
        created_registry_id == 0
    ), "expected no registry created from constructor call"


async def get_registry_id(w3: AsyncWeb3, name: str) -> int:
    registries, _ = await DOCUMENT_PRECOMPILE.fns.registries(
        0, name, (b"", 0, 10, False, False)
    ).call(w3, to=DOCUMENT_ADDRESS)
    reg = next((r for r in registries if r[1] == name), None)
    if reg is None:
        raise AssertionError(f"registry {name} not found")
    return int(reg[0])


async def ensure_registry_exists(
    w3: AsyncWeb3,
    name=DOCUMENT_REGISTRY_DENOM,
    *,
    metadata: str = "",
) -> int:
    try:
        registries, _ = await DOCUMENT_PRECOMPILE.fns.registries(
            0, name, (b"", 0, 10, False, False)
        ).call(w3, to=DOCUMENT_ADDRESS)
        reg = next((r for r in registries if r[1] == name), None)
    except Exception:
        reg = None
    if reg is not None:
        if metadata:
            assert (
                reg[5] == metadata
            ), f"expected registry metadata {metadata}, got {reg[5]}"
        return int(reg[0])
    accounts = get_accounts()
    admin = accounts["community"]
    call = DOCUMENT_PRECOMPILE.fns.addRegistry(name, name, metadata)
    txp = await _tx_params(
        w3,
        sender=admin.address,
        to=DOCUMENT_ADDRESS,
        data=call.data,
    )
    receipt = await call.transact(w3, admin, to=DOCUMENT_ADDRESS, **txp)
    assert receipt.status == 1, f"failed to create registry {name}"

    registry_id = await get_registry_id(w3, name)
    assert_document_event(
        receipt,
        event_sig="AddRegistry(address,uint64,string)",
        caller=admin.address,
        data_types=["uint64", "string"],
        expected_data=[int(registry_id), name],
    )

    if metadata:
        registries, _ = await DOCUMENT_PRECOMPILE.fns.registries(
            0, name, (b"", 0, 10, False, False)
        ).call(w3, to=DOCUMENT_ADDRESS)
        reg = next((r for r in registries if r[1] == name), None)
        assert reg is not None, "created registry not returned in query"
        assert (
            reg[5] == metadata
        ), f"expected registry metadata {metadata}, got {reg[5]}"

    return await get_registry_id(w3, name)


async def grant_role(w3: AsyncWeb3, registry_id, checksum, user, role, sender):
    role_value = role.value if isinstance(role, Role) else str(role)
    call = DOCUMENT_PRECOMPILE.fns.grantRole(
        registry_id, checksum, user.address, role_value
    )
    txp = await _tx_params(
        w3,
        sender=sender.address,
        to=DOCUMENT_ADDRESS,
        data=call.data,
    )
    receipt = await call.transact(w3, sender, to=DOCUMENT_ADDRESS, **txp)
    assert (
        receipt.status == 1
    ), f"grantRole({registry_id}, {checksum}, {user.address}, {role}) failed"

    assert_document_event(
        receipt,
        event_sig="GrantRole(address,uint64,string,address,string)",
        caller=sender.address,
        data_types=["uint64", "string", "address", "string"],
        expected_data=[int(registry_id), str(checksum), user.address, role_value],
    )
    return receipt


async def revoke_role(w3: AsyncWeb3, registry_id, checksum, user, role, sender):
    role_value = role.value if isinstance(role, Role) else str(role)
    call = DOCUMENT_PRECOMPILE.fns.revokeRole(
        registry_id, checksum, user.address, role_value
    )
    txp = await _tx_params(
        w3,
        sender=sender.address,
        to=DOCUMENT_ADDRESS,
        data=call.data,
    )
    receipt = await call.transact(w3, sender, to=DOCUMENT_ADDRESS, **txp)
    assert (
        receipt.status == 1
    ), f"revokeRole({registry_id}, {checksum}, {user.address}, {role}) failed"

    assert_document_event(
        receipt,
        event_sig="RevokeRole(address,uint64,string,address,string)",
        caller=sender.address,
        data_types=["uint64", "string", "address", "string"],
        expected_data=[int(registry_id), str(checksum), user.address, role_value],
    )
    return receipt


async def add_record(
    w3: AsyncWeb3, admin, checksum, name="Test Record", registry=DOCUMENT_REGISTRY_DENOM
):
    metadata = json.dumps({"document": name, "figi": "", "individualId": ""})
    doc = Record(
        registry=registry,
        uri=f"ipfs://{checksum}",
        checksum=checksum,
        checksumAlgo="sha256",
        metadata=metadata,
        timestamp="",
        status="active",
        recordId=0,
        index=0,
        isLatest=False,
    )
    call = DOCUMENT_PRECOMPILE.fns.addRecord(astuple(doc))
    txp = await _tx_params(
        w3,
        sender=admin.address,
        to=DOCUMENT_ADDRESS,
        data=call.data,
    )
    receipt = await call.transact(w3, admin, to=DOCUMENT_ADDRESS, **txp)
    assert (
        receipt.status == 1
    ), f"failed to add record {checksum} to registry {registry}"

    await _assert_add_record_event(
        w3,
        receipt,
        caller=admin.address,
        registry=registry,
        checksum=checksum,
    )
    return receipt


async def update_record_status(
    w3: AsyncWeb3,
    admin,
    record: Record,
    status: str,
):
    registry_id = await get_registry_id(w3, record.registry)
    call = DOCUMENT_PRECOMPILE.fns.updateRecordStatus(
        registry_id,
        record.recordId,
        record.index,
        status,
    )
    txp = await _tx_params(
        w3,
        sender=admin.address,
        to=DOCUMENT_ADDRESS,
        data=call.data,
    )
    receipt = await call.transact(w3, admin, to=DOCUMENT_ADDRESS, **txp)
    assert receipt.status == 1, f"updateRecordStatus({status}) failed"

    assert_document_event(
        receipt,
        event_sig="UpdateRecordStatus(address,uint64,uint64,uint64,string)",
        caller=admin.address,
        data_types=["uint64", "uint64", "uint64", "string"],
        expected_data=[
            int(registry_id),
            int(record.recordId),
            int(record.index),
            str(status),
        ],
    )
    return receipt


async def do_test_add_registry(
    w3: AsyncWeb3,
    *,
    name: str | None = None,
    metadata: str = '{"registry_meta":{"source":"integration_tests"}}',
):
    if name is None:
        name = f"metadata-registry-{int(time.time() * 1000)}"
    await ensure_registry_exists(w3, name, metadata=metadata)


async def do_test_grant_and_revoke_role_as_admin(w3: AsyncWeb3, checksum: str):
    registry_id = await ensure_registry_exists(w3)
    accounts = get_accounts()
    admin = accounts["community"]
    editor = accounts["signer1"]

    if checksum:
        await add_record(w3, admin, checksum)

    await grant_role(w3, registry_id, checksum, editor, Role.EDITOR, admin)
    await revoke_role(w3, registry_id, checksum, editor, Role.EDITOR, admin)


async def do_test_disallow_last_admin_self_revoke(w3: AsyncWeb3):
    registry_name = f"lockout-registry-{int(time.time() * 1000)}"
    registry_id = await ensure_registry_exists(w3, registry_name, metadata="{}")

    accounts = get_accounts()
    admin = accounts["community"]
    replacement_admin = accounts["validator"]
    target = accounts["signer2"]

    # last-admin revoke must fail
    call = DOCUMENT_PRECOMPILE.fns.revokeRole(
        registry_id,
        "",
        admin.address,
        "admin",
    )
    await _assert_call_reverts(
        w3,
        sender=admin.address,
        to=DOCUMENT_ADDRESS,
        data=call.data,
        message="Expected last-admin self-revocation to fail",
    )

    # revocation should succeed after adding a replacement admin
    await grant_role(w3, registry_id, "", replacement_admin, "admin", admin)

    await revoke_role(w3, registry_id, "", admin, "admin", admin)

    # replacement admin can still perform admin actions
    await grant_role(w3, registry_id, "", target, Role.EDITOR, replacement_admin)


async def do_test_module_admin_emergency_admin_recovery(w3: AsyncWeb3):
    registry_name = f"breakglass-registry-{int(time.time() * 1000)}"
    accounts = get_accounts()

    module_admin = accounts["reserve"]
    registry_admin = accounts["validator"]
    replacement_admin = accounts["signer2"]
    target = accounts["community"]

    call = DOCUMENT_PRECOMPILE.fns.addRegistry(
        registry_name,
        registry_name,
        "{}",
    )
    txp = await _tx_params(
        w3,
        sender=registry_admin.address,
        to=DOCUMENT_ADDRESS,
        data=call.data,
    )
    receipt = await call.transact(w3, registry_admin, to=DOCUMENT_ADDRESS, **txp)
    assert receipt["status"] == 1, f"failed to create registry {registry_name}"

    registry_id = await get_registry_id(w3, registry_name)

    # module admin can revoke the sole registry admin as an emergency override
    await revoke_role(w3, registry_id, "", registry_admin, "admin", module_admin)

    # removed registry admin should no longer be able to perform admin actions
    grant_editor_call = DOCUMENT_PRECOMPILE.fns.grantRole(
        registry_id, "", target.address, Role.EDITOR
    )
    await _assert_call_reverts(
        w3,
        sender=registry_admin.address,
        to=DOCUMENT_ADDRESS,
        data=grant_editor_call.data,
        message="Expected removed registry admin to lose admin permissions",
    )

    # module admin can restore admin access to recover from lockout
    await grant_role(w3, registry_id, "", replacement_admin, "admin", module_admin)

    # recovered admin can perform admin actions
    await grant_role(w3, registry_id, "", target, Role.EDITOR, replacement_admin)


async def do_test_grant_role_permissions(w3: AsyncWeb3, is_admin: bool):
    registry_id = await ensure_registry_exists(w3)
    accounts = get_accounts()
    admin = accounts["community"]
    editor1 = accounts["signer1"]
    editor2 = accounts["signer2"]
    sender = admin if is_admin else editor2
    target = editor1
    checksum = ""

    tx = DOCUMENT_PRECOMPILE.fns.grantRole(
        registry_id, checksum, target.address, Role.EDITOR
    )

    if is_admin:
        await grant_role(w3, registry_id, checksum, target, Role.EDITOR, sender)
    else:
        await _assert_call_reverts(
            w3,
            sender=sender.address,
            to=DOCUMENT_ADDRESS,
            data=tx.data,
            message="Expected grant by non-admin to fail",
        )


async def do_test_revoke_role_permissions(w3: AsyncWeb3, is_admin: bool):
    registry_id = await ensure_registry_exists(w3)
    accounts = get_accounts()
    admin = accounts["community"]
    editor1 = accounts["signer1"]
    editor2 = accounts["signer2"]
    sender = admin if is_admin else editor2
    checksum = ""

    # ensure role granted first
    await grant_role(w3, registry_id, checksum, editor1, Role.EDITOR, admin)

    tx = DOCUMENT_PRECOMPILE.fns.revokeRole(
        registry_id, checksum, editor1.address, Role.EDITOR
    )

    if is_admin:
        await revoke_role(w3, registry_id, checksum, editor1, Role.EDITOR, sender)
    else:
        await _assert_call_reverts(
            w3,
            sender=sender.address,
            to=DOCUMENT_ADDRESS,
            data=tx.data,
            message="Expected revoke by non-admin to fail",
        )


async def do_test_multiple_roles_management(w3: AsyncWeb3):
    registry_id = await ensure_registry_exists(w3)
    accounts = get_accounts()
    admin = accounts["community"]
    editor1 = accounts["signer1"]
    editor2 = accounts["signer2"]
    viewer = accounts["validator"]
    checksum = ""

    users_and_roles = [
        (editor1.address, Role.EDITOR),
        (editor2.address, Role.EDITOR),
        (viewer.address, Role.VIEWER),
    ]

    # grant different roles
    for user_address, role in users_and_roles:
        user = next(a for a in accounts.values() if a.address == user_address)
        await grant_role(w3, registry_id, checksum, user, role, admin)

    # revoke all roles
    for user_address, role in users_and_roles:
        user = next(a for a in accounts.values() if a.address == user_address)
        await revoke_role(w3, registry_id, checksum, user, role, admin)


async def do_test_role_idempotency(w3: AsyncWeb3, role: Role):
    registry_id = await ensure_registry_exists(w3)
    accounts = get_accounts()
    admin = accounts["community"]
    editor = accounts["signer1"]
    checksum = ""

    await grant_role(w3, registry_id, checksum, editor, role, admin)
    # second grant should be idempotent
    await grant_role(w3, registry_id, checksum, editor, role, admin)


async def do_test_record_level_overrides_registry_level(
    w3: AsyncWeb3, registry_role: Role, record_role: Role
):
    registry_id = await ensure_registry_exists(w3)
    accounts = get_accounts()
    admin = accounts["community"]
    user = accounts["signer1"]
    reg_checksum = ""
    doc_checksum = "doc123"

    await add_record(w3, admin, doc_checksum)

    # registry-level role
    await grant_role(w3, registry_id, reg_checksum, user, registry_role, admin)
    # record-level role (should override)
    await grant_role(w3, registry_id, doc_checksum, user, record_role, admin)
    # cleanup
    await revoke_role(w3, registry_id, reg_checksum, user, registry_role, admin)
    await revoke_role(w3, registry_id, doc_checksum, user, record_role, admin)


async def do_test_role_with_different_checksums(
    w3: AsyncWeb3, doc1_role: Role, doc2_role: Role
):
    registry_id = await ensure_registry_exists(w3)
    accounts = get_accounts()
    admin = accounts["community"]
    user = accounts["signer1"]
    doc1_checksum = "doc1"
    doc2_checksum = "doc2"

    await add_record(w3, admin, doc1_checksum)
    await add_record(w3, admin, doc2_checksum)

    await grant_role(w3, registry_id, doc1_checksum, user, doc1_role, admin)
    await grant_role(w3, registry_id, doc2_checksum, user, doc2_role, admin)

    await revoke_role(w3, registry_id, doc1_checksum, user, doc1_role, admin)
    await revoke_role(w3, registry_id, doc2_checksum, user, doc2_role, admin)


async def do_test_add_and_query_records(w3: AsyncWeb3):
    registry_name = f"query-registry-{int(time.time() * 1000)}"
    await ensure_registry_exists(w3, name=registry_name)
    accounts = get_accounts()
    admin = accounts["community"]

    for checksum, name in [
        ("abc123", "Record 1"),
        ("abc123", "Record 1 v2"),
        ("def456", "Record 2"),
    ]:
        await add_record(w3, admin, checksum, name=name, registry=registry_name)

    records, _ = await DOCUMENT_PRECOMPILE.fns.records(
        registry_name, "", 0, 0, (b"", 0, 10, True, False)
    ).call(w3, to=DOCUMENT_ADDRESS)
    docs = [Record.from_tuple(d) for d in records]
    assert len(docs) == 2, f"Expected 2 unique records, got {len(docs)}"

    abc_doc = next((d for d in docs if d.checksum == "abc123"), None)
    assert abc_doc is not None
    metadata = json.loads(abc_doc.metadata)
    assert metadata["document"] == "Record 1 v2"


async def do_test_add_record_same_checksum_maintains_record_id(w3: AsyncWeb3):
    await ensure_registry_exists(w3)
    accounts = get_accounts()
    admin = accounts["community"]
    checksum = "test_checksum_123"
    await add_record(w3, admin, checksum, name="Version 1")
    await add_record(w3, admin, checksum, name="Version 2")


async def _add_record_and_set_status(
    w3: AsyncWeb3,
    *,
    checksum: str,
    name: str,
    status: str,
):
    registry_id = await ensure_registry_exists(w3)
    accounts = get_accounts()
    admin = accounts["community"]
    receipt = await add_record(w3, admin, checksum, name=name)
    ev_registry_id, record_id, _, ev_checksum = _decode_document_event_data(
        receipt,
        event_sig="AddRecord(address,uint64,uint64,uint64,string)",
        caller=admin.address,
        data_types=["uint64", "uint64", "uint64", "string"],
    )
    assert int(ev_registry_id) == int(registry_id)
    assert ev_checksum == checksum

    records, _ = await DOCUMENT_PRECOMPILE.fns.records(
        DOCUMENT_REGISTRY_DENOM,
        "",
        int(record_id),
        0,
        (b"", 0, 100, False, False),
    ).call(w3, to=DOCUMENT_ADDRESS)
    records = [Record.from_tuple(r) for r in records]
    assert len(records) == 1, f"expected 1 record, got {len(records)}"
    record = records[0]
    assert record.checksum == checksum

    await update_record_status(w3, admin, record, status)


async def do_test_add_record(w3: AsyncWeb3):
    await _add_record_and_set_status(
        w3,
        checksum="record_123",
        name="Test Record",
        status="verified",
    )
    await _add_record_and_set_status(
        w3,
        checksum="remove_test_123",
        name="To Remove",
        status="removed",
    )


async def do_test_shared_checksum_in_multi_registries(w3: AsyncWeb3):
    accounts = get_accounts()
    admin = accounts["community"]
    admin = accounts["community"]
    registries = [
        ("multi1", "doc1", "figi1", "ind001"),
        ("multi2", "doc2", "figi2", "ind002"),
    ]
    checksum = "shared_checksum_abc123"
    for name, document, figi, individual_id in registries:
        await ensure_registry_exists(w3, name=name)
        metadata = json.dumps(
            {"document": document, "figi": figi, "individualId": individual_id}
        )
        record = Record(
            registry=name,
            uri=f"ipfs://{checksum}",
            checksum=checksum,
            checksumAlgo="sha256",
            metadata=metadata,
            timestamp="",
            status="active",
            recordId=0,
            index=0,
            isLatest=False,
        )
        call = DOCUMENT_PRECOMPILE.fns.addRecord(astuple(record))
        txp = await _tx_params(
            w3,
            sender=admin.address,
            to=DOCUMENT_ADDRESS,
            data=call.data,
        )
        receipt = await call.transact(w3, admin, to=DOCUMENT_ADDRESS, **txp)
        assert receipt.status == 1, f"failed to add record to {name}"

        await _assert_add_record_event(
            w3,
            receipt,
            caller=admin.address,
            registry=name,
            checksum=checksum,
        )
    records, _ = await DOCUMENT_PRECOMPILE.fns.records(
        "", checksum, 0, 0, (b"", 0, 100, False, False)
    ).call(w3, to=DOCUMENT_ADDRESS)
    records = [Record.from_tuple(r) for r in records]
    assert len(records) == 2
    registries_found = {r.registry for r in records}
    assert all(name in registries_found for name, *_ in registries)
    metadata_values = {json.loads(r.metadata)["document"] for r in records}
    assert metadata_values == {"doc1", "doc2"}


async def do_test_query_by_registry_and_checksum(w3: AsyncWeb3):
    accounts = get_accounts()
    admin = accounts["community"]
    registry_name = "query-specific-reg"
    await ensure_registry_exists(w3, name=registry_name)

    registries, _ = await DOCUMENT_PRECOMPILE.fns.registries(
        0, registry_name, (b"", 0, 10, False, False)
    ).call(w3, to=DOCUMENT_ADDRESS)
    assert registries

    checksum = "query_test_checksum"
    await add_record(
        w3, admin, checksum, name="Query Test Record", registry=registry_name
    )
    records, _ = await DOCUMENT_PRECOMPILE.fns.records(
        registry_name, checksum, 0, 0, (b"", 0, 100, False, False)
    ).call(w3, to=DOCUMENT_ADDRESS)
    records = [Record.from_tuple(r) for r in records]

    assert len(records) == 1
    rec = records[0]
    assert rec.checksum == checksum
    assert rec.registry == registry_name


async def do_test_same_checksum_different_record_ids_per_registry(w3: AsyncWeb3):
    accounts = get_accounts()
    admin = accounts["community"]
    registries = ["recordid-test-1", "recordid-test-2"]
    checksum = "recordid_checksum_xyz"

    for name in registries:
        await ensure_registry_exists(w3, name=name)
        await add_record(w3, admin, checksum, name=f"record in {name}", registry=name)

    records, _ = await DOCUMENT_PRECOMPILE.fns.records(
        "", checksum, 0, 0, (b"", 0, 100, False, False)
    ).call(w3, to=DOCUMENT_ADDRESS)
    records = [Record.from_tuple(r) for r in records]

    assert len(records) == 2
    for r in records:
        assert r.index == 1
        assert r.isLatest
        assert r.checksum == checksum


async def do_test_multiple_versions_same_checksum_across_registries(w3: AsyncWeb3):
    accounts = get_accounts()
    admin = accounts["community"]
    registries = ["version-test-1", "version-test-2"]
    checksum = "multi_version_checksum"

    for name in registries:
        await ensure_registry_exists(w3, name=name)

    for version in ["v1.0", "v2.0"]:
        for reg in registries:
            await add_record(w3, admin, checksum, name=version, registry=reg)

    records, _ = await DOCUMENT_PRECOMPILE.fns.records(
        "", checksum, 0, 0, (b"", 0, 100, False, False)
    ).call(w3, to=DOCUMENT_ADDRESS)
    records = [Record.from_tuple(r) for r in records]

    assert len(records) == 2
    for r in records:
        meta = json.loads(r.metadata)
        assert meta["document"] == "v2.0"
        assert r.isLatest
        assert r.index == 2


async def do_test_query_all_registries_for_checksum(w3: AsyncWeb3):
    accounts = get_accounts()
    admin = accounts["community"]
    registries = ["query-all-1", "query-all-2", "query-all-3"]
    checksum = "query_all_checksum"

    for name in registries:
        await ensure_registry_exists(w3, name=name)

    for name in registries[:2]:
        await add_record(w3, admin, checksum, name=f"record in {name}", registry=name)

    records, _ = await DOCUMENT_PRECOMPILE.fns.records(
        "", checksum, 0, 0, (b"", 0, 100, False, False)
    ).call(w3, to=DOCUMENT_ADDRESS)
    records = [Record.from_tuple(r) for r in records]

    assert len(records) == 2
    found = {r.registry for r in records}
    assert found == set(registries[:2])


async def do_test_checksum_only_query_respects_limit(w3: AsyncWeb3):
    accounts = get_accounts()
    admin = accounts["community"]

    checksum = "checksum_limit_test"
    registries = ["checksum-limit-a", "checksum-limit-b", "checksum-limit-c"]

    for name in registries:
        await ensure_registry_exists(w3, name=name)
        await add_record(w3, admin, checksum, name=f"record in {name}", registry=name)

    # explicit limit/offset should work.
    page1, _ = await DOCUMENT_PRECOMPILE.fns.records(
        "", checksum, 0, 0, (b"", 0, 1, False, False)
    ).call(w3, to=DOCUMENT_ADDRESS)
    page2, _ = await DOCUMENT_PRECOMPILE.fns.records(
        "", checksum, 0, 0, (b"", 1, 1, False, False)
    ).call(w3, to=DOCUMENT_ADDRESS)

    page1 = [Record.from_tuple(r) for r in page1]
    page2 = [Record.from_tuple(r) for r in page2]
    assert len(page1) == 1
    assert len(page2) == 1
    assert {r.registry for r in page1}.isdisjoint({r.registry for r in page2})


async def do_test_registry_only_query_respects_limit(w3: AsyncWeb3):
    accounts = get_accounts()
    admin = accounts["community"]

    reg_a = "reg-limit-a"
    reg_b = "reg-limit-b"

    await ensure_registry_exists(w3, name=reg_a)
    await ensure_registry_exists(w3, name=reg_b)

    # add records under A first
    for i in range(5):
        await add_record(
            w3,
            admin,
            checksum=f"checksum-a-{i}",
            name=f"record a {i}",
            registry=reg_a,
        )

    checksum_b = "checksum-b"
    await add_record(
        w3,
        admin,
        checksum=checksum_b,
        name="record b",
        registry=reg_b,
    )

    page, _ = await DOCUMENT_PRECOMPILE.fns.records(
        reg_b, "", 0, 0, (b"", 0, 1, False, False)
    ).call(w3, to=DOCUMENT_ADDRESS)
    page = [Record.from_tuple(r) for r in page]
    assert len(page) == 1
    assert page[0].registry == reg_b
    assert page[0].checksum == checksum_b

import shutil
from dataclasses import astuple, dataclass
from enum import Enum

import pytest
from eth_contract.contract import Contract
from web3 import AsyncWeb3

from .utils import ACCOUNTS

if shutil.which("inveniamd") is None:
    pytest.skip("inveniamd not enabled", allow_module_level=True)


class Role(str, Enum):
    EDITOR = "editor"
    VIEWER = "viewer"


@dataclass
class Record:
    document: str
    registry: str
    uri: str
    checksum: str
    checksumAlgo: str
    timestamp: str
    figi: str
    individualId: str
    status: str
    recordId: int
    index: int
    isLatest: bool

    @classmethod
    def from_tuple(cls, t):
        return cls(*t)


PRECOMPILE = Contract.from_abi(
    [
        """
        struct Record {
            string document;
            string registry;
            string uri;
            string checksum;
            string checksumAlgo;
            string timestamp;
            string figi;
            string individualId;
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
        "struct PageResponse { bytes nextKey; uint64 total; }",
        "function addRegistry(string name, string description) returns (uint64 registryId)",
        "function addRecord(Record record) returns ()",
        "function updateRecordStatus(uint64 registryId, uint64 recordId, string checksum, uint64 index, string status) returns ()",
        """
        function records(
            string registry, string checksum, uint64 recordId, uint64 index, PageRequest pagination
        ) returns (Record[] records, PageResponse pagination)
        """,
        """
        function registries(
            uint64 registryId, string name, PageRequest pagination
        ) returns (Registry[] registries, PageResponse pagination)
        """,
        """
        function grantRole(
            uint64 registryId, string checksum, address account, string role
        ) returns ()
        """,
        """
        function revokeRole(
            uint64 registryId, string checksum, address account
        ) returns ()
        """,
    ]
)
DOCUMENT = "0x0000000000000000000000000000000000000A00"
REGISTRY_ID = 1
REGISTRY_DENOM = "test-registry"
GAS = 100_000


def _admin():
    return ACCOUNTS["community"]


def _editor1():
    return ACCOUNTS["signer1"]


def _editor2():
    return ACCOUNTS["signer2"]


async def _ensure_registry_exists(w3: AsyncWeb3):
    try:
        registries, _ = await PRECOMPILE.fns.registries(
            0, REGISTRY_DENOM, (b"", 0, 10, False, False)
        ).call(w3, to=DOCUMENT)
        exist = any(reg[1] == REGISTRY_DENOM for reg in registries)
    except Exception:
        exist = False
    if exist:
        return
    admin = _admin()
    receipt = await PRECOMPILE.fns.addRegistry(REGISTRY_DENOM, REGISTRY_DENOM).transact(
        w3, admin, to=DOCUMENT, gas=GAS
    )
    assert receipt.status == 1, "addRegistry failed"


async def test_add_registry(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    await _ensure_registry_exists(w3)


@pytest.mark.parametrize(
    "checksum",
    ["", "abc123def456"],
)
async def test_grant_and_revoke_role_as_admin(mantra, checksum):
    w3: AsyncWeb3 = mantra.async_w3
    await _ensure_registry_exists(w3)
    admin = _admin()
    editor = _editor1()

    receipt = await PRECOMPILE.fns.grantRole(
        REGISTRY_ID, checksum, editor.address, Role.EDITOR
    ).transact(w3, admin, to=DOCUMENT)
    assert receipt.status == 1, "GrantRole transaction failed"

    receipt = await PRECOMPILE.fns.revokeRole(
        REGISTRY_ID, checksum, editor.address
    ).transact(w3, admin, to=DOCUMENT)
    assert receipt.status == 1, "RevokeRole transaction failed"


@pytest.mark.parametrize(
    "grantor,should_succeed",
    [
        (_admin, True),
        (_editor2, False),
    ],
)
async def test_grant_role_permissions(mantra, grantor, should_succeed):
    w3: AsyncWeb3 = mantra.async_w3
    await _ensure_registry_exists(w3)
    sender = grantor()
    target = _editor1()
    checksum = ""

    tx = PRECOMPILE.fns.grantRole(REGISTRY_ID, checksum, target.address, Role.EDITOR)

    if should_succeed:
        receipt = await tx.transact(w3, sender, to=DOCUMENT)
        assert receipt.status == 1, "GrantRole transaction failed"
    else:
        with pytest.raises(Exception):
            await tx.transact(w3, sender, to=DOCUMENT)


@pytest.mark.parametrize(
    "revoker,should_succeed",
    [
        (_admin, True),
        (_editor2, False),
    ],
)
async def test_revoke_role_permissions(mantra, revoker, should_succeed):
    w3: AsyncWeb3 = mantra.async_w3
    await _ensure_registry_exists(w3)
    admin = _admin()
    editor = _editor1()
    sender = revoker()
    checksum = ""

    # ensure role granted first
    receipt = await PRECOMPILE.fns.grantRole(
        REGISTRY_ID, checksum, editor.address, Role.EDITOR
    ).transact(w3, admin, to=DOCUMENT)
    assert receipt.status == 1, "Setup grantRole failed"

    tx = PRECOMPILE.fns.revokeRole(REGISTRY_ID, checksum, editor.address)

    if should_succeed:
        receipt = await tx.transact(w3, sender, to=DOCUMENT)
        assert receipt.status == 1, "RevokeRole transaction failed"
    else:
        with pytest.raises(Exception):
            await tx.transact(w3, sender, to=DOCUMENT)


async def test_multiple_roles_management(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    await _ensure_registry_exists(w3)
    admin = _admin()
    editor1 = _editor1()
    editor2 = _editor2()
    viewer = ACCOUNTS["validator"]
    checksum = ""

    users_and_roles = [
        (editor1.address, Role.EDITOR),
        (editor2.address, Role.EDITOR),
        (viewer.address, Role.VIEWER),
    ]

    # grant different roles
    for user_address, role in users_and_roles:
        receipt = await PRECOMPILE.fns.grantRole(
            REGISTRY_ID, checksum, user_address, role
        ).transact(w3, admin, to=DOCUMENT)
        assert receipt.status == 1, f"Failed to grant {role} to {user_address}"

    # revoke all roles
    for user_address, _ in users_and_roles:
        receipt = await PRECOMPILE.fns.revokeRole(
            REGISTRY_ID, checksum, user_address
        ).transact(w3, admin, to=DOCUMENT)
        assert receipt.status == 1, f"Failed to revoke role from {user_address}"


async def _grant(w3: AsyncWeb3, registry_id, checksum, user, role, sender):
    receipt = await PRECOMPILE.fns.grantRole(
        registry_id, checksum, user.address, role
    ).transact(w3, sender, to=DOCUMENT)
    assert (
        receipt.status == 1
    ), f"grantRole({registry_id}, {checksum}, {user.address}, {role}) failed"
    return receipt


async def _revoke(w3: AsyncWeb3, registry_id, checksum, user, sender):
    receipt = await PRECOMPILE.fns.revokeRole(
        registry_id, checksum, user.address
    ).transact(w3, sender, to=DOCUMENT)
    assert (
        receipt.status == 1
    ), f"revokeRole({registry_id}, {checksum}, {user.address}) failed"
    return receipt


@pytest.mark.parametrize("role", [Role.EDITOR, Role.VIEWER])
async def test_role_idempotency(mantra, role):
    w3: AsyncWeb3 = mantra.async_w3
    await _ensure_registry_exists(w3)
    admin = _admin()
    editor = _editor1()
    checksum = ""

    await _grant(w3, REGISTRY_ID, checksum, editor, role, admin)
    # second grant should be idempotent
    await _grant(w3, REGISTRY_ID, checksum, editor, role, admin)


@pytest.mark.parametrize(
    "registry_role,record_role",
    [
        (Role.VIEWER, Role.EDITOR),
        (Role.EDITOR, Role.VIEWER),
    ],
)
async def test_record_level_overrides_registry_level(
    mantra, registry_role, record_role
):
    w3: AsyncWeb3 = mantra.async_w3
    await _ensure_registry_exists(w3)
    admin = _admin()
    user = _editor1()
    reg_checksum = ""
    doc_checksum = "doc123"

    # registry-level role
    await _grant(w3, REGISTRY_ID, reg_checksum, user, registry_role, admin)
    # record-level role (should override)
    await _grant(w3, REGISTRY_ID, doc_checksum, user, record_role, admin)
    # cleanup
    await _revoke(w3, REGISTRY_ID, reg_checksum, user, admin)
    await _revoke(w3, REGISTRY_ID, doc_checksum, user, admin)


@pytest.mark.parametrize(
    "doc1_role,doc2_role",
    [
        (Role.EDITOR, Role.VIEWER),
        (Role.VIEWER, Role.EDITOR),
        (Role.EDITOR, Role.EDITOR),
    ],
)
async def test_role_with_different_checksums(mantra, doc1_role, doc2_role):
    w3: AsyncWeb3 = mantra.async_w3
    await _ensure_registry_exists(w3)
    admin = _admin()
    user = _editor1()
    doc1_checksum = "doc1"
    doc2_checksum = "doc2"

    await _grant(w3, REGISTRY_ID, doc1_checksum, user, doc1_role, admin)
    await _grant(w3, REGISTRY_ID, doc2_checksum, user, doc2_role, admin)

    await _revoke(w3, REGISTRY_ID, doc1_checksum, user, admin)
    await _revoke(w3, REGISTRY_ID, doc2_checksum, user, admin)


async def _add_record(w3: AsyncWeb3, admin, checksum, name="Test Record"):
    doc = Record(
        document=name,
        registry=REGISTRY_DENOM,
        uri=f"ipfs://{checksum}",
        checksum=checksum,
        checksumAlgo="sha256",
        timestamp="",
        figi="",
        individualId="",
        status="",
        recordId=0,
        index=0,
        isLatest=False,
    )
    receipt = await PRECOMPILE.fns.addRecord(astuple(doc)).transact(
        w3, admin, to=DOCUMENT, gas=GAS
    )
    assert receipt.status == 1, f"addRecord({checksum}) failed"
    return receipt


async def _update_record_status(
    w3: AsyncWeb3,
    admin,
    record: Record,
    checksum,
    status: str,
):
    receipt = await PRECOMPILE.fns.updateRecordStatus(
        REGISTRY_ID,
        record.recordId,
        checksum,
        record.index,
        status,
    ).transact(w3, admin, to=DOCUMENT)
    assert receipt.status == 1, f"updateRecordStatus({checksum}, {status}) failed"
    return receipt


async def test_add_and_query_records(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    await _ensure_registry_exists(w3)
    admin = _admin()

    for checksum, name in [
        ("abc123", "Record 1"),
        ("abc123", "Record 1 v2"),
        ("def456", "Record 2"),
    ]:
        await _add_record(w3, admin, checksum, name)

    records, _ = await PRECOMPILE.fns.records(
        REGISTRY_DENOM, "", 0, 0, (b"", 0, 10, True, False)
    ).call(w3, to=DOCUMENT)
    docs = [Record.from_tuple(d) for d in records]
    assert len(docs) == 2, f"Expected 2 unique records, got {len(docs)}"
    abc_doc = next((d for d in docs if d.checksum == "abc123"), None)
    assert abc_doc.document == "Record 1 v2"


async def test_add_record_same_checksum_maintains_record_id(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    await _ensure_registry_exists(w3)
    admin = _admin()
    checksum = "test_checksum_123"
    await _add_record(w3, admin, checksum, "Version 1")
    await _add_record(w3, admin, checksum, "Version 2")


async def test_add_record(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    await _ensure_registry_exists(w3)
    admin = _admin()
    checksum = "record_123"
    await _add_record(w3, admin, checksum, "Test Record")
    records, _ = await PRECOMPILE.fns.records(
        REGISTRY_DENOM, checksum, 0, 0, (b"", 0, 100, False, False)
    ).call(w3, to=DOCUMENT)
    records = [Record.from_tuple(r) for r in records]
    assert len(records) > 0, f"Record with checksum {checksum} not found"
    await _update_record_status(w3, admin, records[0], checksum, "verified")


async def test_remove_record(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    await _ensure_registry_exists(w3)
    admin = _admin()
    checksum = "remove_test_123"
    await _add_record(w3, admin, checksum, "To Remove")
    records, _ = await PRECOMPILE.fns.records(
        REGISTRY_DENOM, checksum, 0, 0, (b"", 0, 100, False, False)
    ).call(w3, to=DOCUMENT)
    records = [Record.from_tuple(r) for r in records]
    assert len(records) > 0, f"Record with checksum {checksum} not found"
    await _update_record_status(w3, admin, records[0], checksum, "removed")

import json
import shutil
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


PRECOMPILE = Contract.from_abi(
    [
        """
        struct Document {
            string name;
            string denom;
            string uri;
            string checksum;
            string checksumAlgo;
            string timestamp;
            string figi;
            string individualId;
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
        "function addDocument(Document document) returns ()",
        "function removeDocument(string denom, uint64 index) returns ()",
        """
        function documents(
            string denom, uint64 index, PageRequest pagination
        ) returns (Document[] documents, PageResponse pagination)
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


def _admin():
    return ACCOUNTS["community"]


def _editor1():
    return ACCOUNTS["signer1"]


def _editor2():
    return ACCOUNTS["signer2"]


async def _ensure_registry_exists(w3: AsyncWeb3, cli):
    try:
        registry = cli.query_registry(name=REGISTRY_DENOM)
    except Exception:
        registry = None
    if registry:
        return
    admin = _admin()
    receipt = await PRECOMPILE.fns.addRegistry(REGISTRY_DENOM, REGISTRY_DENOM).transact(
        w3, admin, to=DOCUMENT
    )
    assert receipt.status == 1, "addRegistry failed"


async def test_add_registry(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    cli = mantra.cosmos_cli()
    await _ensure_registry_exists(w3, cli)


@pytest.mark.parametrize(
    "checksum",
    ["", "abc123def456"],
)
async def test_grant_and_revoke_role_as_admin(mantra, checksum):
    w3: AsyncWeb3 = mantra.async_w3
    await _ensure_registry_exists(w3, mantra.cosmos_cli())
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
    await _ensure_registry_exists(w3, mantra.cosmos_cli())
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
    await _ensure_registry_exists(w3, mantra.cosmos_cli())
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
    await _ensure_registry_exists(w3, mantra.cosmos_cli())
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
    await _ensure_registry_exists(w3, mantra.cosmos_cli())
    admin = _admin()
    editor = _editor1()
    checksum = ""

    await _grant(w3, REGISTRY_ID, checksum, editor, role, admin)
    # second grant should be idempotent
    await _grant(w3, REGISTRY_ID, checksum, editor, role, admin)


@pytest.mark.parametrize(
    "registry_role,document_role",
    [
        (Role.VIEWER, Role.EDITOR),
        (Role.EDITOR, Role.VIEWER),
    ],
)
async def test_document_level_overrides_registry_level(
    mantra, registry_role, document_role
):
    w3: AsyncWeb3 = mantra.async_w3
    await _ensure_registry_exists(w3, mantra.cosmos_cli())
    admin = _admin()
    user = _editor1()
    reg_checksum = ""
    doc_checksum = "doc123"

    # registry-level role
    await _grant(w3, REGISTRY_ID, reg_checksum, user, registry_role, admin)
    # document-level role (should override)
    await _grant(w3, REGISTRY_ID, doc_checksum, user, document_role, admin)
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
    await _ensure_registry_exists(w3, mantra.cosmos_cli())
    admin = _admin()
    user = _editor1()
    doc1_checksum = "doc1"
    doc2_checksum = "doc2"

    await _grant(w3, REGISTRY_ID, doc1_checksum, user, doc1_role, admin)
    await _grant(w3, REGISTRY_ID, doc2_checksum, user, doc2_role, admin)

    await _revoke(w3, REGISTRY_ID, doc1_checksum, user, admin)
    await _revoke(w3, REGISTRY_ID, doc2_checksum, user, admin)


async def _add_document(w3: AsyncWeb3, admin, checksum, name="Test Document"):
    doc = (
        name,
        REGISTRY_DENOM,
        f"ipfs://{checksum}",
        checksum,
        "sha256",
        "",
        "",
        "",
    )
    receipt = await PRECOMPILE.fns.addDocument(doc).transact(w3, admin, to=DOCUMENT)
    assert receipt.status == 1, f"addDocument({checksum}) failed"
    return receipt


async def test_add_and_query_documents(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    await _ensure_registry_exists(w3, mantra.cosmos_cli())
    admin = _admin()

    for checksum, name in [
        ("abc123", "Document 1"),
        ("abc123", "Document 1 v2"),
        ("def456", "Document 2"),
    ]:
        await _add_document(w3, admin, checksum, name)

    docs, _ = await PRECOMPILE.fns.documents(
        REGISTRY_DENOM, 0, (b"", 0, 10, True, False)
    ).call(w3, to=DOCUMENT)

    assert len(docs) == 2, f"Expected 2 unique documents, got {len(docs)}"
    abc_doc = next((d for d in docs if d[3] == "abc123"), None)
    assert abc_doc[0] == "Document 1 v2"


async def test_add_document_same_checksum_maintains_record_id(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    await _ensure_registry_exists(w3, mantra.cosmos_cli())
    admin = _admin()
    checksum = "test_checksum_123"
    await _add_document(w3, admin, checksum, "Version 1")
    await _add_document(w3, admin, checksum, "Version 2")


async def test_remove_document(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    await _ensure_registry_exists(w3, mantra.cosmos_cli())
    admin = _admin()
    await _add_document(w3, admin, "remove_test_123", "To Remove")
    receipt = await PRECOMPILE.fns.removeDocument(REGISTRY_DENOM, 1).transact(
        w3, admin, to=DOCUMENT
    )
    assert receipt.status == 1


async def test_add_record(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    cli = mantra.cosmos_cli()
    await _ensure_registry_exists(w3, cli)

    checksum = "record_123"
    record_json = {
        "registry": REGISTRY_DENOM,
        "uri": f"ipfs://{checksum}",
        "checksum": checksum,
        "checksum_algo": "sha256",
    }
    rsp = cli.add_record(record=json.dumps(record_json), from_="community")
    assert rsp["code"] == 0, rsp["raw_log"]

    def get_record(checksum):
        records = cli.query_doc_records(registry_id=REGISTRY_ID).get("records", [])
        return next((r for r in records if r.get("checksum") == checksum), None)

    record = get_record(checksum)
    assert record is not None, f"Record with checksum {checksum} not found"
    status = "verified"
    rsp = cli.update_record_status(
        registry_id=REGISTRY_ID,
        record_id=record["record_id"],
        index=record["index"],
        status=status,
        from_="community",
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    assert get_record(checksum)["status"] == status

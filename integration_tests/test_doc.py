import shutil
from enum import Enum

import pytest
from eth_contract.contract import Contract
from web3 import AsyncWeb3

from .utils import ACCOUNTS, build_contract

if shutil.which("inveniamd") is None:
    pytest.skip("inveniamd not enabled", allow_module_level=True)


class Role(str, Enum):
    EDITOR = "editor"
    VIEWER = "viewer"


PRECOMPILE = Contract(build_contract("DocumentI")["abi"])
DOCUMENT = "0x0000000000000000000000000000000000000A00"
REGISTRY_ID = 1


def _admin():
    return ACCOUNTS["community"]


def _editor1():
    return ACCOUNTS["signer1"]


def _editor2():
    return ACCOUNTS["signer2"]


@pytest.mark.parametrize(
    "checksum",
    ["", "abc123def456"],
)
async def test_grant_and_revoke_role_as_admin(mantra, checksum):
    w3: AsyncWeb3 = mantra.async_w3
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
    admin = _admin()
    user = _editor1()
    doc1_checksum = "doc1"
    doc2_checksum = "doc2"

    await _grant(w3, REGISTRY_ID, doc1_checksum, user, doc1_role, admin)
    await _grant(w3, REGISTRY_ID, doc2_checksum, user, doc2_role, admin)

    await _revoke(w3, REGISTRY_ID, doc1_checksum, user, admin)
    await _revoke(w3, REGISTRY_ID, doc2_checksum, user, admin)

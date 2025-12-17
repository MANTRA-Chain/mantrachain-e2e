import pytest
from eth_contract.contract import Contract
from web3 import AsyncWeb3

from .utils import ACCOUNTS, build_contract

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
    cli = mantra.cosmos_cli()
    if not cli.has_module("document"):
        pytest.skip("document module not enabled")
    w3: AsyncWeb3 = mantra.async_w3
    admin = _admin()
    editor = _editor1()

    receipt = await PRECOMPILE.fns.grantRole(
        REGISTRY_ID, checksum, editor.address, "editor"
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
    cli = mantra.cosmos_cli()
    if not cli.has_module("document"):
        pytest.skip("document module not enabled")
    w3: AsyncWeb3 = mantra.async_w3
    sender = grantor()
    target = _editor1()
    checksum = ""

    tx = PRECOMPILE.fns.grantRole(REGISTRY_ID, checksum, target.address, "editor")

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
    cli = mantra.cosmos_cli()
    if not cli.has_module("document"):
        pytest.skip("document module not enabled")
    w3: AsyncWeb3 = mantra.async_w3
    admin = _admin()
    editor = _editor1()
    sender = revoker()
    checksum = ""

    # ensure role granted first
    receipt = await PRECOMPILE.fns.grantRole(
        REGISTRY_ID, checksum, editor.address, "editor"
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
    cli = mantra.cosmos_cli()
    if not cli.has_module("document"):
        pytest.skip("document module not enabled")
    w3: AsyncWeb3 = mantra.async_w3
    admin = _admin()
    editor1 = _editor1()
    editor2 = _editor2()
    viewer = ACCOUNTS["validator"]
    checksum = ""

    users_and_roles = [
        (editor1.address, "editor"),
        (editor2.address, "editor"),
        (viewer.address, "viewer"),
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

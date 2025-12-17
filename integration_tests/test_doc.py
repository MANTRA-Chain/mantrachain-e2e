import shutil
from pathlib import Path

import pytest
from eth_contract.contract import Contract
from web3 import AsyncWeb3

from .network import setup_custom_mantra
from .utils import ACCOUNTS, build_contract


@pytest.fixture(scope="module")
def custom_mantra(request, tmp_path_factory):
    cmd = "inveniamd"
    if shutil.which(cmd) is None:
        pytest.skip(f"{cmd} not enabled")
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp("doc")
    yield from setup_custom_mantra(
        path,
        27400,
        Path(__file__).parent / "configs/doc.jsonnet",
        chain=chain,
    )


PRECOMPILE = Contract(build_contract("DocumentI")["abi"])
DOCUMENT = "0x0000000000000000000000000000000000000A00"


async def test_grant(custom_mantra):
    w3: AsyncWeb3 = custom_mantra.async_w3
    admin, editor = ACCOUNTS["community"], ACCOUNTS["signer1"]
    registry_id = 1
    checksum = ""
    receipt = await PRECOMPILE.fns.grantRole(
        registry_id, checksum, editor.address, "editor"
    ).transact(w3, admin, to=DOCUMENT)
    assert receipt.status == 1, "GrantRole transaction failed"


async def test_revoke(custom_mantra):
    w3: AsyncWeb3 = custom_mantra.async_w3
    admin = ACCOUNTS["community"]
    editor = ACCOUNTS["signer1"]
    registry_id = 1
    checksum = ""
    grant_tx = PRECOMPILE.fns.grantRole(registry_id, checksum, editor.address, "editor")
    receipt = await grant_tx.transact(w3, admin, to=DOCUMENT)
    assert receipt.status == 1, "Grant role failed"
    receipt = await PRECOMPILE.fns.revokeRole(
        registry_id, checksum, editor.address
    ).transact(w3, admin, to=DOCUMENT)
    assert receipt.status == 1, "RevokeRole transaction failed"


async def test_permission_denied(custom_mantra):
    w3: AsyncWeb3 = custom_mantra.async_w3
    non_admin = ACCOUNTS["signer2"]
    target = ACCOUNTS["signer1"]
    registry_id = 1
    checksum = ""
    # try to grant role as non-admin (should fail)
    tx = PRECOMPILE.fns.grantRole(registry_id, checksum, target.address, "editor")
    with pytest.raises(Exception):
        await tx.transact(w3, non_admin, to=DOCUMENT)


async def test_grant_role_as_admin(custom_mantra):
    w3: AsyncWeb3 = custom_mantra.async_w3
    admin = ACCOUNTS["community"]
    editor = ACCOUNTS["signer1"]
    registry_id = 1
    checksum = ""
    receipt = await PRECOMPILE.fns.grantRole(
        registry_id, checksum, editor.address, "editor"
    ).transact(w3, admin, to=DOCUMENT)
    assert receipt.status == 1, "GrantRole transaction failed"


async def test_grant_role_permission_denied(custom_mantra):
    w3: AsyncWeb3 = custom_mantra.async_w3
    non_admin = ACCOUNTS["signer2"]
    target_user = ACCOUNTS["signer1"]
    registry_id = 1
    checksum = ""
    # try to grant role as non-admin - should fail
    with pytest.raises(Exception):
        await PRECOMPILE.fns.grantRole(
            registry_id, checksum, target_user.address, "editor"
        ).transact(w3, non_admin, to=DOCUMENT)


async def test_revoke_role_as_admin(custom_mantra):
    w3: AsyncWeb3 = custom_mantra.async_w3
    admin = ACCOUNTS["community"]
    editor = ACCOUNTS["signer1"]
    registry_id = 1
    checksum = ""
    receipt = await PRECOMPILE.fns.grantRole(
        registry_id, checksum, editor.address, "editor"
    ).transact(w3, admin, to=DOCUMENT)
    assert receipt.status == 1, "Grant role transaction failed"
    receipt = await PRECOMPILE.fns.revokeRole(
        registry_id, checksum, editor.address
    ).transact(w3, admin, to=DOCUMENT)
    assert receipt.status == 1, "RevokeRole transaction failed"


async def test_revoke_role_permission_denied(custom_mantra):
    w3: AsyncWeb3 = custom_mantra.async_w3
    admin = ACCOUNTS["community"]
    non_admin = ACCOUNTS["signer2"]
    editor = ACCOUNTS["signer1"]
    registry_id = 1
    checksum = ""
    # admin grants a role first
    await PRECOMPILE.fns.grantRole(
        registry_id, checksum, editor.address, "editor"
    ).transact(w3, admin, to=DOCUMENT)
    # try to revoke as non-admin - should fail
    with pytest.raises(Exception):
        await PRECOMPILE.fns.revokeRole(registry_id, checksum, editor.address).transact(
            w3, non_admin, to=DOCUMENT
        )


async def test_document_level_role_management(custom_mantra):
    w3: AsyncWeb3 = custom_mantra.async_w3
    admin = ACCOUNTS["community"]
    editor = ACCOUNTS["signer1"]
    registry_id = 1
    # specific document checksum
    checksum = "abc123def456"
    # grant document-level role
    receipt = await PRECOMPILE.fns.grantRole(
        registry_id, checksum, editor.address, "editor"
    ).transact(w3, admin, to=DOCUMENT)
    assert receipt.status == 1, "Grant document-level role failed"

    # revoke document-level role
    receipt = await PRECOMPILE.fns.revokeRole(
        registry_id, checksum, editor.address
    ).transact(w3, admin, to=DOCUMENT)
    assert receipt.status == 1, "Revoke document-level role failed"


async def test_multiple_roles_management(custom_mantra):
    w3: AsyncWeb3 = custom_mantra.async_w3
    admin = ACCOUNTS["community"]
    editor1 = ACCOUNTS["signer1"]
    editor2 = ACCOUNTS["signer2"]
    viewer = ACCOUNTS["validator"]
    registry_id = 1
    checksum = ""

    # grant different roles to different users
    users_and_roles = [
        (editor1.address, "editor"),
        (editor2.address, "editor"),
        (viewer.address, "viewer"),
    ]

    for user_address, role in users_and_roles:
        receipt = await PRECOMPILE.fns.grantRole(
            registry_id, checksum, user_address, role
        ).transact(w3, admin, to=DOCUMENT)
        assert receipt.status == 1, f"Failed to grant {role} to {user_address}"

    # revoke roles
    for user_address, _ in users_and_roles:
        receipt = await PRECOMPILE.fns.revokeRole(
            registry_id, checksum, user_address
        ).transact(w3, admin, to=DOCUMENT)

        assert receipt.status == 1, f"Failed to revoke role from {user_address}"

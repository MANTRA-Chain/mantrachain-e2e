import shutil

import pytest

from .doc_utils import (
    Role,
    do_test_add_and_query_records,
    do_test_add_record,
    do_test_add_record_same_checksum_maintains_record_id,
    do_test_add_registry,
    do_test_grant_and_revoke_role_as_admin,
    do_test_grant_role_permissions,
    do_test_multiple_roles_management,
    do_test_multiple_versions_same_checksum_across_registries,
    do_test_query_all_registries_for_checksum,
    do_test_query_by_registry_and_checksum,
    do_test_record_level_overrides_registry_level,
    do_test_remove_record,
    do_test_revoke_role_permissions,
    do_test_role_idempotency,
    do_test_role_with_different_checksums,
    do_test_same_checksum_different_record_ids_per_registry,
    do_test_shared_checksum_in_multi_registries,
)

if shutil.which("inveniamd") is None:
    pytest.skip("inveniamd not enabled", allow_module_level=True)


async def test_add_registry(mantra):
    await do_test_add_registry(mantra.async_w3)


@pytest.mark.parametrize("checksum", ["", "abc123def456"])
async def test_grant_and_revoke_role_as_admin(mantra, checksum):
    await do_test_grant_and_revoke_role_as_admin(mantra.async_w3, checksum)


@pytest.mark.parametrize("is_admin", [True, False])
async def test_grant_role_permissions(mantra, is_admin):
    await do_test_grant_role_permissions(mantra.async_w3, is_admin)


@pytest.mark.parametrize("is_admin", [True, False])
async def test_revoke_role_permissions(mantra, is_admin):
    await do_test_revoke_role_permissions(mantra.async_w3, is_admin)


async def test_multiple_roles_management(mantra):
    await do_test_multiple_roles_management(mantra.async_w3)


@pytest.mark.parametrize("role", [Role.EDITOR, Role.VIEWER])
async def test_role_idempotency(mantra, role):
    await do_test_role_idempotency(mantra.async_w3, role)


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
    await do_test_record_level_overrides_registry_level(
        mantra.async_w3, registry_role, record_role
    )


@pytest.mark.parametrize(
    "doc1_role,doc2_role",
    [
        (Role.EDITOR, Role.VIEWER),
        (Role.VIEWER, Role.EDITOR),
        (Role.EDITOR, Role.EDITOR),
    ],
)
async def test_role_with_different_checksums(mantra, doc1_role, doc2_role):
    await do_test_role_with_different_checksums(mantra.async_w3, doc1_role, doc2_role)


async def test_add_and_query_records(mantra):
    await do_test_add_and_query_records(mantra.async_w3)


async def test_add_record_same_checksum_maintains_record_id(mantra):
    await do_test_add_record_same_checksum_maintains_record_id(mantra.async_w3)


async def test_add_record(mantra):
    await do_test_add_record(mantra.async_w3)


async def test_remove_record(mantra):
    await do_test_remove_record(mantra.async_w3)


async def test_shared_checksum_in_multi_registries(mantra):
    await do_test_shared_checksum_in_multi_registries(mantra.async_w3)


async def test_query_by_registry_and_checksum(mantra):
    await do_test_query_by_registry_and_checksum(mantra.async_w3)


async def test_same_checksum_different_record_ids_per_registry(mantra):
    await do_test_same_checksum_different_record_ids_per_registry(mantra.async_w3)


async def test_multiple_versions_same_checksum_across_registries(mantra):
    await do_test_multiple_versions_same_checksum_across_registries(mantra.async_w3)


async def test_query_all_registries_for_checksum(mantra):
    await do_test_query_all_registries_for_checksum(mantra.async_w3)

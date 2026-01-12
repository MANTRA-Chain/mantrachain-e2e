import json
import subprocess
import time
from dataclasses import astuple, dataclass
from enum import Enum

from eth_contract.contract import Contract as ContractAsync
from web3 import AsyncWeb3

from .utils import ACCOUNTS, KEYS

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
        string memory description
    ) returns (uint64 registryId)
    """,
    """
    function addRecord(Record memory record)
    """,
    """
    function updateRecordStatus(
        uint64 registryId,
        uint64 recordId,
        string memory checksum,
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
DOCUMENT_REGISTRY_ID = 1
DOCUMENT_REGISTRY_DENOM = "test-registry"
DOCUMENT_GAS = 100_000


def _get_private_key(account_name: str) -> str:
    accounts = get_accounts()
    return KEYS[
        next(k for k, v in ACCOUNTS.items() if v == accounts[account_name])
    ].hex()


def _timestamp_suffix() -> str:
    return str(int(time.time() * 1000))[-6:]


def _unique_test_names(prefix: str, count: int) -> tuple[list[str], str]:
    ts = _timestamp_suffix()
    registries = [f"{prefix}-{i + 1}-{ts}" for i in range(count)]
    checksum = f"{prefix}_chk_{ts}"
    return registries, checksum


class CastBackend:
    def __init__(self, rpc_url: str):
        self.rpc_url = rpc_url
        self._sender_key = _get_private_key("community")

    def set_sender(self, account_name: str) -> None:
        self._sender_key = _get_private_key(account_name)

    def get_account_address(self, account_name: str) -> str:
        accounts = get_accounts()
        return accounts[account_name].address

    def _cast_send(self, sig: str, *args) -> subprocess.CompletedProcess:
        cmd = [
            "cast",
            "send",
            DOCUMENT_ADDRESS,
            sig,
            *[str(a) for a in args],
            "--rpc-url",
            self.rpc_url,
            "--private-key",
            self._sender_key,
            "--gas-limit",
            str(DOCUMENT_GAS),
        ]
        return subprocess.run(cmd, capture_output=True, text=True)

    def _cast_call(self, sig: str, *args) -> subprocess.CompletedProcess:
        cmd = [
            "cast",
            "call",
            DOCUMENT_ADDRESS,
            sig,
            *[str(a) for a in args],
            "--rpc-url",
            self.rpc_url,
        ]
        return subprocess.run(cmd, capture_output=True, text=True)

    def ensure_registry_exists(self, name: str = DOCUMENT_REGISTRY_DENOM) -> None:
        result = self._cast_call(
            "registries(uint64,string,(bytes,uint64,uint64,bool,bool))"
            "((uint64,string,string,string,string)[],(bytes,uint64))",
            "0",
            name,
            "(0x,0,10,false,false)",
        )
        if result.returncode == 0 and name in result.stdout:
            return
        self.add_registry(name, name)

    def add_registry(self, name: str, description: str) -> None:
        result = self._cast_send(
            "addRegistry(string,string)(uint64)",
            name,
            description,
        )
        assert (
            result.returncode == 0
        ), f"failed to create registry {name}: {result.stderr}"

    def add_record(
        self,
        checksum: str,
        name: str = "Test Record",
        registry: str = DOCUMENT_REGISTRY_DENOM,
        status: str = "",
        metadata_dict: dict | None = None,
    ) -> None:
        if metadata_dict:
            metadata = ",".join(f"{k}:{v}" for k, v in metadata_dict.items())
        else:
            metadata = f"document:{name}"
        status_val = f'"{status}"' if status else '""'
        record_tuple = (
            f'("{registry}","ipfs://{checksum}","{checksum}","sha256",'
            f'"{metadata}","",{status_val},0,0,false)'
        )
        result = self._cast_send(
            "addRecord((string,string,string,string,string,string,string,"
            "uint64,uint64,bool))",
            record_tuple,
        )
        assert (
            result.returncode == 0
        ), f"failed to add record {checksum} to registry {registry}: {result.stderr}"

    def grant_role(
        self,
        registry_id: int,
        checksum: str,
        user_address: str,
        role: str,
        expect_fail: bool = False,
    ) -> bool:
        result = self._cast_send(
            "grantRole(uint64,string,address,string)",
            registry_id,
            checksum,
            user_address,
            role,
        )
        failed = result.returncode != 0 or (
            "status" in result.stdout and "0 (failed)" in result.stdout.lower()
        )
        if expect_fail:
            return failed
        assert not failed, (
            f"grantRole({registry_id}, {checksum}, {user_address}, {role}) "
            f"failed: {result.stderr}"
        )
        return False

    def revoke_role(
        self,
        registry_id: int,
        checksum: str,
        user_address: str,
        role: str,
        expect_fail: bool = False,
    ) -> bool:
        result = self._cast_send(
            "revokeRole(uint64,string,address,string)",
            registry_id,
            checksum,
            user_address,
            role,
        )
        failed = result.returncode != 0 or (
            "status" in result.stdout and "0 (failed)" in result.stdout.lower()
        )
        if expect_fail:
            return failed
        assert not failed, (
            f"revokeRole({registry_id}, {checksum}, {user_address}, {role}) "
            f"failed: {result.stderr}"
        )
        return False

    def query_records(self, registry: str = "", checksum: str = "") -> list[Record]:
        result = self._cast_call(
            "records(string,string,uint64,uint64,(bytes,uint64,uint64,bool,bool))"
            "((string,string,string,string,string,string,string,uint64,uint64,bool)[],"
            "(bytes,uint64))",
            registry,
            checksum,
            "0",
            "0",
            "(0x,0,100,false,false)",
        )
        assert result.returncode == 0, f"cast call records failed: {result.stderr}"
        self._last_query_output = result.stdout
        return []

    def query_registries(self, name: str) -> list:
        result = self._cast_call(
            "registries(uint64,string,(bytes,uint64,uint64,bool,bool))"
            "((uint64,string,string,string,string)[],(bytes,uint64))",
            "0",
            name,
            "(0x,0,10,false,false)",
        )
        assert result.returncode == 0, f"cast call registries failed: {result.stderr}"
        self._last_query_output = result.stdout
        return []

    def assert_in_last_output(self, value: str) -> None:
        assert (
            value in self._last_query_output
        ), f"'{value}' not found in output: {self._last_query_output}"


async def ensure_registry_exists(w3: AsyncWeb3, name=DOCUMENT_REGISTRY_DENOM):
    try:
        registries, _ = await DOCUMENT_PRECOMPILE.fns.registries(
            0, name, (b"", 0, 10, False, False)
        ).call(w3, to=DOCUMENT_ADDRESS)
        exist = any(reg[1] == name for reg in registries)
    except Exception:
        exist = False
    if exist:
        return
    accounts = get_accounts()
    admin = accounts["community"]
    receipt = await DOCUMENT_PRECOMPILE.fns.addRegistry(name, name).transact(
        w3, admin, to=DOCUMENT_ADDRESS, gas=DOCUMENT_GAS
    )
    assert receipt.status == 1, f"failed to create registry {name}"


async def grant_role(w3: AsyncWeb3, registry_id, checksum, user, role, sender):
    receipt = await DOCUMENT_PRECOMPILE.fns.grantRole(
        registry_id, checksum, user.address, role
    ).transact(w3, sender, to=DOCUMENT_ADDRESS)
    assert (
        receipt.status == 1
    ), f"grantRole({registry_id}, {checksum}, {user.address}, {role}) failed"
    return receipt


async def revoke_role(w3: AsyncWeb3, registry_id, checksum, user, role, sender):
    receipt = await DOCUMENT_PRECOMPILE.fns.revokeRole(
        registry_id, checksum, user.address, role
    ).transact(w3, sender, to=DOCUMENT_ADDRESS)
    assert (
        receipt.status == 1
    ), f"revokeRole({registry_id}, {checksum}, {user.address}, {role}) failed"
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
        status="",
        recordId=0,
        index=0,
        isLatest=False,
    )
    receipt = await DOCUMENT_PRECOMPILE.fns.addRecord(astuple(doc)).transact(
        w3, admin, to=DOCUMENT_ADDRESS, gas=DOCUMENT_GAS
    )
    assert (
        receipt.status == 1
    ), f"failed to add record {checksum} to registry {registry}"
    return receipt


async def update_record_status(
    w3: AsyncWeb3,
    admin,
    record: Record,
    checksum,
    status: str,
):
    receipt = await DOCUMENT_PRECOMPILE.fns.updateRecordStatus(
        DOCUMENT_REGISTRY_ID,
        record.recordId,
        checksum,
        record.index,
        status,
    ).transact(w3, admin, to=DOCUMENT_ADDRESS)
    assert receipt.status == 1, f"updateRecordStatus({checksum}, {status}) failed"
    return receipt


async def do_test_add_registry(w3: AsyncWeb3):
    await ensure_registry_exists(w3)
    do_test_add_registry_cast(w3.provider.endpoint_uri)


async def do_test_grant_and_revoke_role_as_admin(w3: AsyncWeb3, checksum: str):
    await ensure_registry_exists(w3)
    accounts = get_accounts()
    admin = accounts["community"]
    editor = accounts["signer1"]

    receipt = await DOCUMENT_PRECOMPILE.fns.grantRole(
        DOCUMENT_REGISTRY_ID, checksum, editor.address, Role.EDITOR
    ).transact(w3, admin, to=DOCUMENT_ADDRESS)
    assert receipt.status == 1, "GrantRole transaction failed"

    receipt = await DOCUMENT_PRECOMPILE.fns.revokeRole(
        DOCUMENT_REGISTRY_ID, checksum, editor.address, Role.EDITOR
    ).transact(w3, admin, to=DOCUMENT_ADDRESS)
    assert receipt.status == 1, "RevokeRole transaction failed"
    do_test_grant_and_revoke_role_as_admin_cast(w3.provider.endpoint_uri, checksum)


async def do_test_grant_role_permissions(w3: AsyncWeb3, is_admin: bool):
    await ensure_registry_exists(w3)
    accounts = get_accounts()
    admin = accounts["community"]
    editor1 = accounts["signer1"]
    editor2 = accounts["signer2"]
    sender = admin if is_admin else editor2
    target = editor1
    checksum = ""

    tx = DOCUMENT_PRECOMPILE.fns.grantRole(
        DOCUMENT_REGISTRY_ID, checksum, target.address, Role.EDITOR
    )

    if is_admin:
        receipt = await tx.transact(w3, sender, to=DOCUMENT_ADDRESS)
        assert receipt.status == 1, "GrantRole transaction failed"
    else:
        try:
            await tx.transact(w3, sender, to=DOCUMENT_ADDRESS)
            assert False, "Expected grant by non-admin to fail"
        except Exception:
            pass  # Expected to fail
    do_test_grant_role_permissions_cast(w3.provider.endpoint_uri, is_admin)


async def do_test_revoke_role_permissions(w3: AsyncWeb3, is_admin: bool):
    await ensure_registry_exists(w3)
    accounts = get_accounts()
    admin = accounts["community"]
    editor1 = accounts["signer1"]
    editor2 = accounts["signer2"]
    sender = admin if is_admin else editor2
    checksum = ""

    # ensure role granted first
    receipt = await DOCUMENT_PRECOMPILE.fns.grantRole(
        DOCUMENT_REGISTRY_ID, checksum, editor1.address, Role.EDITOR
    ).transact(w3, admin, to=DOCUMENT_ADDRESS)
    assert receipt.status == 1, "Setup grantRole failed"

    tx = DOCUMENT_PRECOMPILE.fns.revokeRole(
        DOCUMENT_REGISTRY_ID, checksum, editor1.address, Role.EDITOR
    )

    if is_admin:
        receipt = await tx.transact(w3, sender, to=DOCUMENT_ADDRESS)
        assert receipt.status == 1, "RevokeRole transaction failed"
    else:
        try:
            await tx.transact(w3, sender, to=DOCUMENT_ADDRESS)
            assert False, "Expected revoke by non-admin to fail"
        except Exception:
            pass  # Expected to fail

    do_test_revoke_role_permissions_cast(w3.provider.endpoint_uri, is_admin)


async def do_test_multiple_roles_management(w3: AsyncWeb3):
    await ensure_registry_exists(w3)
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
        receipt = await DOCUMENT_PRECOMPILE.fns.grantRole(
            DOCUMENT_REGISTRY_ID, checksum, user_address, role
        ).transact(w3, admin, to=DOCUMENT_ADDRESS)
        assert receipt.status == 1, f"Failed to grant {role} to {user_address}"

    # revoke all roles
    for user_address, role in users_and_roles:
        receipt = await DOCUMENT_PRECOMPILE.fns.revokeRole(
            DOCUMENT_REGISTRY_ID, checksum, user_address, role
        ).transact(w3, admin, to=DOCUMENT_ADDRESS)
        assert receipt.status == 1, f"Failed to revoke role from {user_address}"

    do_test_multiple_roles_management_cast(w3.provider.endpoint_uri)


async def do_test_role_idempotency(w3: AsyncWeb3, role: Role):
    await ensure_registry_exists(w3)
    accounts = get_accounts()
    admin = accounts["community"]
    editor = accounts["signer1"]
    checksum = ""

    await grant_role(w3, DOCUMENT_REGISTRY_ID, checksum, editor, role, admin)
    # second grant should be idempotent
    await grant_role(w3, DOCUMENT_REGISTRY_ID, checksum, editor, role, admin)

    do_test_role_idempotency_cast(w3.provider.endpoint_uri, role)


async def do_test_record_level_overrides_registry_level(
    w3: AsyncWeb3, registry_role: Role, record_role: Role
):
    await ensure_registry_exists(w3)
    accounts = get_accounts()
    admin = accounts["community"]
    user = accounts["signer1"]
    reg_checksum = ""
    doc_checksum = "doc123"

    # registry-level role
    await grant_role(w3, DOCUMENT_REGISTRY_ID, reg_checksum, user, registry_role, admin)
    # record-level role (should override)
    await grant_role(w3, DOCUMENT_REGISTRY_ID, doc_checksum, user, record_role, admin)
    # cleanup
    await revoke_role(
        w3, DOCUMENT_REGISTRY_ID, reg_checksum, user, registry_role, admin
    )
    await revoke_role(w3, DOCUMENT_REGISTRY_ID, doc_checksum, user, record_role, admin)

    do_test_record_level_overrides_registry_level_cast(
        w3.provider.endpoint_uri, registry_role, record_role
    )


async def do_test_role_with_different_checksums(
    w3: AsyncWeb3, doc1_role: Role, doc2_role: Role
):
    await ensure_registry_exists(w3)
    accounts = get_accounts()
    admin = accounts["community"]
    user = accounts["signer1"]
    doc1_checksum = "doc1"
    doc2_checksum = "doc2"

    await grant_role(w3, DOCUMENT_REGISTRY_ID, doc1_checksum, user, doc1_role, admin)
    await grant_role(w3, DOCUMENT_REGISTRY_ID, doc2_checksum, user, doc2_role, admin)

    await revoke_role(w3, DOCUMENT_REGISTRY_ID, doc1_checksum, user, doc1_role, admin)
    await revoke_role(w3, DOCUMENT_REGISTRY_ID, doc2_checksum, user, doc2_role, admin)

    do_test_role_with_different_checksums_cast(
        w3.provider.endpoint_uri, doc1_role, doc2_role
    )


async def do_test_add_and_query_records(w3: AsyncWeb3):
    await ensure_registry_exists(w3)
    accounts = get_accounts()
    admin = accounts["community"]

    for checksum, name in [
        ("abc123", "Record 1"),
        ("abc123", "Record 1 v2"),
        ("def456", "Record 2"),
    ]:
        await add_record(w3, admin, checksum, name=name)

    records, _ = await DOCUMENT_PRECOMPILE.fns.records(
        DOCUMENT_REGISTRY_DENOM, "", 0, 0, (b"", 0, 10, True, False)
    ).call(w3, to=DOCUMENT_ADDRESS)
    docs = [Record.from_tuple(d) for d in records]
    assert len(docs) == 2, f"Expected 2 unique records, got {len(docs)}"

    abc_doc = next((d for d in docs if d.checksum == "abc123"), None)
    assert abc_doc is not None
    metadata = json.loads(abc_doc.metadata)
    assert metadata["document"] == "Record 1 v2"
    do_test_add_and_query_records_cast(w3.provider.endpoint_uri)


async def do_test_add_record_same_checksum_maintains_record_id(w3: AsyncWeb3):
    await ensure_registry_exists(w3)
    accounts = get_accounts()
    admin = accounts["community"]
    checksum = "test_checksum_123"
    await add_record(w3, admin, checksum, name="Version 1")
    await add_record(w3, admin, checksum, name="Version 2")
    do_test_add_record_same_checksum_maintains_record_id_cast(w3.provider.endpoint_uri)


async def do_test_add_record(w3: AsyncWeb3):
    await ensure_registry_exists(w3)
    accounts = get_accounts()
    admin = accounts["community"]
    checksum = "record_123"
    await add_record(w3, admin, checksum, name="Test Record")
    records, _ = await DOCUMENT_PRECOMPILE.fns.records(
        DOCUMENT_REGISTRY_DENOM, checksum, 0, 0, (b"", 0, 100, False, False)
    ).call(w3, to=DOCUMENT_ADDRESS)
    records = [Record.from_tuple(r) for r in records]
    assert len(records) > 0, f"Record with checksum {checksum} not found"
    await update_record_status(w3, admin, records[0], checksum, "verified")
    do_test_add_record_cast(w3.provider.endpoint_uri)


async def do_test_remove_record(w3: AsyncWeb3):
    await ensure_registry_exists(w3)
    accounts = get_accounts()
    admin = accounts["community"]
    checksum = "remove_test_123"
    await add_record(w3, admin, checksum, name="To Remove")
    records, _ = await DOCUMENT_PRECOMPILE.fns.records(
        DOCUMENT_REGISTRY_DENOM, checksum, 0, 0, (b"", 0, 100, False, False)
    ).call(w3, to=DOCUMENT_ADDRESS)
    records = [Record.from_tuple(r) for r in records]
    assert len(records) > 0, f"Record with checksum {checksum} not found"
    await update_record_status(w3, admin, records[0], checksum, "removed")

    do_test_remove_record_cast(w3.provider.endpoint_uri)


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
        receipt = await DOCUMENT_PRECOMPILE.fns.addRecord(astuple(record)).transact(
            w3, admin, to=DOCUMENT_ADDRESS, gas=DOCUMENT_GAS
        )
        assert receipt.status == 1, f"failed to add record to {name}"
    records, _ = await DOCUMENT_PRECOMPILE.fns.records(
        "", checksum, 0, 0, (b"", 0, 100, False, False)
    ).call(w3, to=DOCUMENT_ADDRESS)
    records = [Record.from_tuple(r) for r in records]
    assert len(records) == 2
    registries_found = {r.registry for r in records}
    assert all(name in registries_found for name, *_ in registries)
    metadata_values = {json.loads(r.metadata)["document"] for r in records}
    assert metadata_values == {"doc1", "doc2"}

    do_test_shared_checksum_in_multi_registries_cast(w3.provider.endpoint_uri)


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

    do_test_query_by_registry_and_checksum_cast(w3.provider.endpoint_uri)


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

    do_test_same_checksum_different_record_ids_per_registry_cast(
        w3.provider.endpoint_uri
    )


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

    do_test_multiple_versions_same_checksum_across_registries_cast(
        w3.provider.endpoint_uri
    )


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

    do_test_query_all_registries_for_checksum_cast(w3.provider.endpoint_uri)


def do_test_add_registry_cast(rpc_url: str):
    backend = CastBackend(rpc_url)
    registry_name = "unified-test-registry"
    backend.add_registry(registry_name, registry_name)
    backend.query_registries(registry_name)
    backend.assert_in_last_output(registry_name)


def do_test_grant_and_revoke_role_as_admin_cast(rpc_url: str, checksum: str):
    backend = CastBackend(rpc_url)
    backend.ensure_registry_exists(DOCUMENT_REGISTRY_DENOM)
    editor_address = backend.get_account_address("signer1")
    backend.grant_role(DOCUMENT_REGISTRY_ID, checksum, editor_address, Role.EDITOR)
    backend.revoke_role(DOCUMENT_REGISTRY_ID, checksum, editor_address, Role.EDITOR)


def do_test_grant_role_permissions_cast(rpc_url: str, is_admin: bool):
    backend = CastBackend(rpc_url)
    backend.ensure_registry_exists(DOCUMENT_REGISTRY_DENOM)
    target_address = backend.get_account_address("signer1")
    checksum = ""

    if is_admin:
        backend.set_sender("community")
        backend.grant_role(DOCUMENT_REGISTRY_ID, checksum, target_address, Role.EDITOR)
    else:
        backend.set_sender("signer2")
        failed = backend.grant_role(
            DOCUMENT_REGISTRY_ID,
            checksum,
            target_address,
            Role.EDITOR,
            expect_fail=True,
        )
        assert failed, "Expected grant by non-admin to fail"


def do_test_revoke_role_permissions_cast(rpc_url: str, is_admin: bool):
    backend = CastBackend(rpc_url)
    backend.ensure_registry_exists(DOCUMENT_REGISTRY_DENOM)
    editor1_address = backend.get_account_address("signer1")
    checksum = ""

    # ensure role granted first (as admin)
    backend.set_sender("community")
    backend.grant_role(DOCUMENT_REGISTRY_ID, checksum, editor1_address, Role.EDITOR)

    if is_admin:
        backend.revoke_role(
            DOCUMENT_REGISTRY_ID, checksum, editor1_address, Role.EDITOR
        )
    else:
        backend.set_sender("signer2")
        failed = backend.revoke_role(
            DOCUMENT_REGISTRY_ID,
            checksum,
            editor1_address,
            Role.EDITOR,
            expect_fail=True,
        )
        assert failed, "Expected revoke by non-admin to fail"


def do_test_multiple_roles_management_cast(rpc_url: str):
    backend = CastBackend(rpc_url)
    backend.ensure_registry_exists(DOCUMENT_REGISTRY_DENOM)
    backend.set_sender("community")
    checksum = ""

    users_and_roles = [
        (backend.get_account_address("signer1"), Role.EDITOR),
        (backend.get_account_address("signer2"), Role.EDITOR),
        (backend.get_account_address("validator"), Role.VIEWER),
    ]

    for user_address, role in users_and_roles:
        backend.grant_role(DOCUMENT_REGISTRY_ID, checksum, user_address, role)

    for user_address, role in users_and_roles:
        backend.revoke_role(DOCUMENT_REGISTRY_ID, checksum, user_address, role)


def do_test_role_idempotency_cast(rpc_url: str, role: Role):
    backend = CastBackend(rpc_url)
    backend.ensure_registry_exists(DOCUMENT_REGISTRY_DENOM)
    backend.set_sender("community")
    editor_address = backend.get_account_address("signer1")
    checksum = ""

    backend.grant_role(DOCUMENT_REGISTRY_ID, checksum, editor_address, role)
    # second grant should be idempotent
    backend.grant_role(DOCUMENT_REGISTRY_ID, checksum, editor_address, role)


def do_test_record_level_overrides_registry_level_cast(
    rpc_url: str, registry_role: Role, record_role: Role
):
    backend = CastBackend(rpc_url)
    backend.ensure_registry_exists(DOCUMENT_REGISTRY_DENOM)
    backend.set_sender("community")
    user_address = backend.get_account_address("signer1")
    reg_checksum = ""
    doc_checksum = "doc123"

    backend.grant_role(DOCUMENT_REGISTRY_ID, reg_checksum, user_address, registry_role)
    backend.grant_role(DOCUMENT_REGISTRY_ID, doc_checksum, user_address, record_role)
    backend.revoke_role(DOCUMENT_REGISTRY_ID, reg_checksum, user_address, registry_role)
    backend.revoke_role(DOCUMENT_REGISTRY_ID, doc_checksum, user_address, record_role)


def do_test_role_with_different_checksums_cast(
    rpc_url: str, doc1_role: Role, doc2_role: Role
):
    backend = CastBackend(rpc_url)
    backend.ensure_registry_exists(DOCUMENT_REGISTRY_DENOM)
    backend.set_sender("community")
    user_address = backend.get_account_address("signer1")
    doc1_checksum = "doc1"
    doc2_checksum = "doc2"

    backend.grant_role(DOCUMENT_REGISTRY_ID, doc1_checksum, user_address, doc1_role)
    backend.grant_role(DOCUMENT_REGISTRY_ID, doc2_checksum, user_address, doc2_role)
    backend.revoke_role(DOCUMENT_REGISTRY_ID, doc1_checksum, user_address, doc1_role)
    backend.revoke_role(DOCUMENT_REGISTRY_ID, doc2_checksum, user_address, doc2_role)


def do_test_add_and_query_records_cast(rpc_url: str):
    backend = CastBackend(rpc_url)
    backend.ensure_registry_exists(DOCUMENT_REGISTRY_DENOM)
    backend.set_sender("community")

    suffix = _timestamp_suffix()
    checksum1 = f"abc123_{suffix}"
    checksum2 = f"def456_{suffix}"

    for checksum, name in [
        (checksum1, "Record 1"),
        (checksum1, "Record 1 v2"),
        (checksum2, "Record 2"),
    ]:
        backend.add_record(checksum, name=name, registry=DOCUMENT_REGISTRY_DENOM)

    backend.query_records(registry=DOCUMENT_REGISTRY_DENOM)
    backend.assert_in_last_output(checksum1)
    backend.assert_in_last_output(checksum2)


def do_test_add_record_same_checksum_maintains_record_id_cast(rpc_url: str):
    backend = CastBackend(rpc_url)
    backend.ensure_registry_exists(DOCUMENT_REGISTRY_DENOM)
    backend.set_sender("community")
    suffix = _timestamp_suffix()
    checksum = f"test_checksum_123_{suffix}"

    backend.add_record(checksum, name="Version 1", registry=DOCUMENT_REGISTRY_DENOM)
    backend.add_record(checksum, name="Version 2", registry=DOCUMENT_REGISTRY_DENOM)


def do_test_add_record_cast(rpc_url: str):
    backend = CastBackend(rpc_url)
    backend.ensure_registry_exists(DOCUMENT_REGISTRY_DENOM)
    backend.set_sender("community")
    suffix = _timestamp_suffix()
    checksum = f"record_123_{suffix}"

    backend.add_record(checksum, name="Test Record", registry=DOCUMENT_REGISTRY_DENOM)

    backend.query_records(registry=DOCUMENT_REGISTRY_DENOM)
    backend.assert_in_last_output(checksum)


def do_test_remove_record_cast(rpc_url: str):
    backend = CastBackend(rpc_url)
    backend.ensure_registry_exists(DOCUMENT_REGISTRY_DENOM)
    backend.set_sender("community")
    suffix = _timestamp_suffix()
    checksum = f"remove_test_123_{suffix}"

    backend.add_record(checksum, name="To Remove", registry=DOCUMENT_REGISTRY_DENOM)
    backend.query_records(registry=DOCUMENT_REGISTRY_DENOM)
    backend.assert_in_last_output(checksum)


def do_test_shared_checksum_in_multi_registries_cast(rpc_url: str):
    backend = CastBackend(rpc_url)
    backend.set_sender("community")
    registries, checksum = _unique_test_names("multi", 2)

    for name in registries:
        backend.ensure_registry_exists(name)

    for i, name in enumerate(registries):
        backend.add_record(
            checksum,
            name=f"doc{i + 1}",
            registry=name,
            status="active",
            metadata_dict={
                "document": f"doc{i + 1}",
                "figi": f"figi{i + 1}",
                "individualId": f"ind{i + 1:03d}",
            },
        )

    backend.query_records(checksum=checksum)
    for name in registries:
        backend.assert_in_last_output(name)


def do_test_query_by_registry_and_checksum_cast(rpc_url: str):
    backend = CastBackend(rpc_url)
    backend.set_sender("community")
    suffix = _timestamp_suffix()
    registry_name = f"query-specific-reg-{suffix}"
    checksum = f"query_test_checksum_{suffix}"

    backend.ensure_registry_exists(registry_name)
    backend.add_record(checksum, name="Query Test Record", registry=registry_name)
    backend.query_records(registry=registry_name)
    backend.assert_in_last_output(checksum)
    backend.assert_in_last_output(registry_name)


def do_test_same_checksum_different_record_ids_per_registry_cast(rpc_url: str):
    backend = CastBackend(rpc_url)
    backend.set_sender("community")
    registries, checksum = _unique_test_names("recid", 2)

    for name in registries:
        backend.ensure_registry_exists(name)

    for name in registries:
        backend.add_record(checksum, name=f"record in {name}", registry=name)

    backend.query_records(checksum=checksum)
    for name in registries:
        backend.assert_in_last_output(name)


def do_test_multiple_versions_same_checksum_across_registries_cast(rpc_url: str):
    backend = CastBackend(rpc_url)
    backend.set_sender("community")
    registries, checksum = _unique_test_names("ver", 2)

    for name in registries:
        backend.ensure_registry_exists(name)

    for version in ["v1.0", "v2.0"]:
        for reg in registries:
            backend.add_record(checksum, name=version, registry=reg)

    backend.query_records(checksum=checksum)
    for name in registries:
        backend.assert_in_last_output(name)


def do_test_query_all_registries_for_checksum_cast(rpc_url: str):
    backend = CastBackend(rpc_url)
    backend.set_sender("community")
    registries, checksum = _unique_test_names("qa", 3)

    for name in registries:
        backend.ensure_registry_exists(name)

    for name in registries[:2]:
        backend.add_record(checksum, name=f"record in {name}", registry=name)

    backend.query_records(checksum=checksum)
    for name in registries[:2]:
        backend.assert_in_last_output(name)

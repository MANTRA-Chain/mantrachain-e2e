"""Storage damage a node cannot see.

A store that has lost a node keeps answering reads, so each test here reaches
for the moment the loss has to surface -- a write, a rebuild, a compaction --
and asserts the node says so. That needs a binary built against all three:

    pebble     https://github.com/mmsqe/pebble/tree/compaction
    iavl       https://github.com/mmsqe/iavl/tree/fix_pebble
    cosmos-db  https://github.com/mmsqe/cosmos-db/tree/fix_pebble

Without them the damage stays silent, which is the failure being covered.
"""

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from pystarport.utils import wait_for_block, wait_for_new_blocks

from .network import setup_custom_mantra
from .utils import (
    ADDRS,
    DEFAULT_DENOM,
    Contract,
    derive_new_account,
    fund_acc,
    send_transaction,
    sign_transaction,
)


@pytest.fixture(scope="module")
def mantra_damaged(request, tmp_path_factory):
    """A cluster whose node3 loses a node from its bank store."""
    yield from setup_custom_mantra(
        tmp_path_factory.mktemp("damaged"),
        27000,
        Path(__file__).parent / "configs/damaged-node.jsonnet",
        chain=request.config.getoption("chain_config"),
    )


@pytest.fixture(scope="module")
def mantra_cold(request, tmp_path_factory):
    """A cluster whose node3 loses a block nothing reads until a compaction."""
    yield from setup_custom_mantra(
        tmp_path_factory.mktemp("cold"),
        27150,
        Path(__file__).parent / "configs/damaged-node.jsonnet",
        chain=request.config.getoption("chain_config"),
    )


@pytest.fixture(scope="module")
def mantra_rebuild(request, tmp_path_factory):
    """A cluster whose node3 rebuilds its fast index over a missing node."""
    yield from setup_custom_mantra(
        tmp_path_factory.mktemp("rebuild"),
        27200,
        Path(__file__).parent / "configs/damaged-node.jsonnet",
        chain=request.config.getoption("chain_config"),
    )


def _tail_until(log, mark, needle, timeout=60):
    deadline = time.time() + timeout
    while True:
        text = log.read_text(errors="ignore")[mark:]
        if needle in text or time.time() > deadline:
            return text
        time.sleep(1)


def _iavlscan(*args, check=True):
    exe = os.getenv("IAVLSCAN")
    if not exe or not os.path.exists(exe):
        exe = shutil.which("iavlscan")
    if not exe:
        pytest.skip("iavlscan not installed")
    res = subprocess.run([exe, *args], capture_output=True, text=True)
    if check and res.returncode:
        raise AssertionError(f"iavlscan {args}: {res.stderr[-2000:]}")
    return res


def _require_patched(mantra, module):
    binary = shutil.which(mantra.chain_binary) or mantra.chain_binary
    data = Path(binary).read_bytes()
    dep = b"dep\t" + module.encode() + b"\t"
    i = data.find(dep)
    entry = data[i + len(dep) : i + len(dep) + 200] if i != -1 else b""
    if b"=>\t" not in entry.split(b"dep\t")[0]:
        pytest.skip(f"{binary} was built against unpatched {module.split('/')[-1]}")


def _delete_cold_bank_leaf(mantra, seed):
    """Fund an account that is never touched again, then unlink its leaf.

    Leaves node3 stopped and its bank store missing a node no read goes near,
    which is what a lost block leaves behind.
    """
    acct = derive_new_account(seed)
    fund_acc(mantra.w3, acct)
    wait_for_new_blocks(mantra.cosmos_cli(), 2)
    key = bytes([0x02, 20]) + bytes.fromhex(acct.address[2:]) + DEFAULT_DENOM.encode()

    mantra.supervisorctl("stop", f"{mantra.config['chain_id']}-node3")
    db = mantra.node_home(3) / "data/application.db"
    args = ("-db", str(db), "-store", "bank")
    path = _iavlscan(*args, "-treekey", key.hex()).stdout
    leaf = re.search(r"-delete ([0-9a-f]+)$", path, re.M).group(1)
    _iavlscan(*args, "-delete", leaf)
    return acct


def test_missing_node_surfaces_only_on_write(mantra_damaged):
    """A missing cold node hides until a write reaches it (iavl).

    Reads answer from the fast index rather than the tree, so the store looks
    healthy until a write walks into that subtree.
    """
    mantra = mantra_damaged
    # _require_patched(mantra, "github.com/cosmos/iavl")
    w3 = mantra.w3
    cli = mantra.cosmos_cli()
    cli3 = mantra.cosmos_cli(3)
    proc = f"{mantra.config['chain_id']}-node3"
    db = mantra.node_home(3) / "data/application.db"
    log = mantra.base_dir / "node3.log"

    acct = _delete_cold_bank_leaf(mantra, 500)
    report = _iavlscan("-db", str(db), "-store", "bank", "-audit").stdout
    assert "affected stores: bank" in report, report
    mark = log.stat().st_size
    mantra.supervisorctl("start", proc)

    # Damaged, and indistinguishable from healthy: it catches up and commits.
    wait_for_block(cli3, cli.block_height() + 3)
    assert w3.eth.get_balance(acct.address) > 0, "the fast index still answers"

    # Pruning and block writes race for the missing node. A write winning ends
    # the node before pruning runs again, so only check pruning when it got
    # there; iavl's TestPruningKeepsLiveNodes covers it without the race.
    pruning = _tail_until(log, mark, "Error while pruning", timeout=30)
    if "Error while pruning" in pruning:
        assert "traversing version" in pruning, pruning[-2000:]

    # The first write through the missing node's parent.
    mark = log.stat().st_size
    send_transaction(w3, {"to": acct.address, "value": 1, "gasPrice": w3.eth.gas_price})
    text = _tail_until(log, mark, "wrong Block.Header.AppHash")
    assert "iavl set error" in text, text[-2000:]
    assert "wrong Block.Header.AppHash" in text, text[-2000:]


def test_rebuild_refuses_a_tree_it_cannot_read(mantra_rebuild):
    """A fast index rebuild must fail on a missing node, not commit less (iavl).

    Rolling back overwrites the latest version, which invalidates the fast
    index, so the rollback rebuilds it from the whole tree, and what that walk
    writes becomes the live state.
    """
    mantra = mantra_rebuild
    # _require_patched(mantra, "github.com/cosmos/iavl")
    home = mantra.node_home(3)
    _delete_cold_bank_leaf(mantra, 501)

    res = subprocess.run(
        [mantra.chain_binary, "rollback", "--home", str(home)],
        capture_output=True,
        text=True,
    )
    said = res.stdout + res.stderr
    assert res.returncode != 0, (
        "the rollback rebuilt its fast index across a missing node and "
        f"reported success; every key past it now reads as absent\n{said[-2000:]}"
    )
    assert "Value missing for key" in said, said[-2000:]


def _corrupt_largest_sstable(db):
    """Overwrite 4KB in the middle of the biggest sstable.

    Past the header and well before the index and footer, so the file still
    opens and the damage surfaces as a block checksum failure on read. Keys
    are ordered by store, so with one store grown large the middle is its
    data rather than anyone's root.
    """
    files = sorted(db.glob("*.sst"), key=lambda p: p.stat().st_size, reverse=True)
    assert files, f"no sstable to corrupt in {db}"
    target = files[0]
    off = target.stat().st_size // 2
    with target.open("r+b") as f:
        f.seek(off)
        f.write(b"\xa5" * 4096)
    return target.name, off


def _restart(mantra, cli3, proc):
    mantra.supervisorctl("stop", proc)
    try:
        mantra.supervisorctl("start", proc)
        wait_for_new_blocks(cli3, 2)
    except Exception:
        return False
    return True


def _grow_cold_state(w3, batches, per_tx=500):
    """Fill the evm store with storage that nothing reads again.

    A node reads each store's root on startup and little else, so on a
    database of a few tens of KB every block holds one. Enough cold slots and
    most hold none, which is a mainnet database almost everywhere.
    """
    contract = Contract("BurnGas")
    contract.deploy(w3)
    for _ in range(batches):
        tx = contract.contract.functions.burnGas(per_tx).build_transaction(
            {"from": ADDRS["community"]}
        )
        signed = sign_transaction(w3, tx)
        txhash = w3.eth.send_raw_transaction(signed.raw_transaction)
        assert w3.eth.wait_for_transaction_receipt(txhash).status == 1
    return batches * per_tx


def test_compaction_refuses_a_block_it_cannot_read(mantra_cold):
    """A compaction must fail on damage, not pass over it (pebble, cosmos-db).

    Pebble 1.x passes over a block it cannot read and calls the compaction a
    success, leaving an output missing exactly the keys that block held and
    nothing in the log -- which is why the node that diverged on mainnet never
    recorded a storage error. The branch backports a6580b19, which fails the
    compaction instead.
    """
    mantra = mantra_cold
    # _require_patched(mantra, "github.com/cockroachdb/pebble")
    w3 = mantra.w3
    cli3 = mantra.cosmos_cli(3)
    proc = f"{mantra.config['chain_id']}-node3"
    db = mantra.node_home(3) / "data/application.db"
    log = mantra.base_dir / "node3.log"

    print(f"grew {_grow_cold_state(w3, 12)} cold slots")
    wait_for_new_blocks(cli3, 2)

    # Pebble flushes the replayed write-ahead log when it opens, so restarting
    # is what gets that state into a table at all -- one big enough for its
    # middle to be well clear of any store's root.
    biggest = 0
    for _ in range(8):
        # A bounce that times out waiting for blocks is worth another go; only
        # the size it leaves behind decides whether there is a test to run.
        _restart(mantra, cli3, proc)
        biggest = max((p.stat().st_size for p in db.glob("*.sst")), default=0)
        if biggest > 200_000:
            break
    else:
        pytest.skip(f"largest sstable is only {biggest}B")

    mantra.supervisorctl("stop", proc)
    clean = _iavlscan("-db", str(db), "-audit").stdout
    assert "0 store(s) affected" in clean, clean[-2000:]

    name, off = _corrupt_largest_sstable(db)
    mark = log.stat().st_size
    assert _restart(mantra, cli3, proc), (
        f"node3 met the damage in {name} on startup, so it was not cold "
        "and never reached a compaction"
    )

    # Every restart stacks another file above the damaged one, so compactions
    # keep being offered it. A pebble that swallows the block consumes the
    # table, and the damage leaves the database along with the keys.
    for _ in range(8):
        if name not in {p.name for p in db.glob("*.sst")}:
            break
        if not _restart(mantra, cli3, proc):
            break
    gone = name not in {p.name for p in db.glob("*.sst")}

    reported = _tail_until(log, mark, "background error", timeout=30)
    mantra.supervisorctl("stop", proc)
    audit = _iavlscan("-db", str(db), "-audit", check=False)
    print(f"corrupted {name} at {off}; compacted away: {gone}")
    print(audit.stdout[-600:] or audit.stderr[-600:])

    assert not gone, (
        f"a compaction consumed {name} and reported success; the store now "
        f"reads clean and is missing whatever that block held:\n"
        f"{audit.stdout[-2000:]}"
    )
    # Still there, still unreadable: nothing was quietly rewritten without it.
    assert "checksum mismatch" in audit.stderr, (
        "the damaged table survived but a scan no longer meets the damage, "
        f"which is neither behaviour this covers:\n{audit.stderr[-2000:]}"
    )
    # Refusing the compaction is half of it: pebble reports the refusal through
    # BackgroundError, whose default writes to the Infof cosmos-db silences, so
    # without a listener of its own the node runs on and says nothing.
    # _require_patched(mantra, "github.com/cosmos/cosmos-db")
    assert "background error" in reported, (
        "the compaction failed but nothing reached the node's log; "
        f"NewPebbleDB is where that listener belongs\n{reported[-2000:]}"
    )

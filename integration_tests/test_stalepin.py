import configparser
import os
import re
import time
from pathlib import Path

import pytest
from pystarport import cluster
from pystarport.utils import wait_for_block

from .network import setup_custom_mantra
from .utils import ADDRS, CMD, KEYS, derive_new_account, send_transaction

pytestmark = pytest.mark.slow

MISSING_NODE_ERR = "Value missing for key"
APPHASH_ERR = "wrong Block.Header.AppHash"

NODE = 3


@pytest.fixture(scope="module")
def mantra(request, tmp_path_factory):
    yield from setup_custom_mantra(
        tmp_path_factory.mktemp("stalepin"),
        27100,
        Path(__file__).parent / "configs/stalepin.jsonnet",
        chain=request.config.getoption("chain_config"),
    )


def _restart_frozen(clustercli, chain_dir, n):
    """Start node NODE with its refresher frozen after n notifications, as a
    dropped subscription would leave it. Scoped to one program so the validators
    keep refreshing; the pin rebuilds on every start.
    """
    ini_path = chain_dir / cluster.SUPERVISOR_CONFIG_FILE
    ini = configparser.RawConfigParser()
    ini.read(ini_path)
    proc = f"{clustercli.chain_id}-node{NODE}"
    assert ini.has_section(f"program:{proc}"), f"no {proc} in {ini_path}"
    ini.set(f"program:{proc}", "environment", f"EVM_MEMPOOL_FREEZE_CTX_AFTER={n}")
    with ini_path.open("w") as fp:
        ini.write(fp)

    clustercli.supervisor.reloadConfig()
    # Stop before removing, each call is tolerant: node may already be down or gone
    for step in ("stopProcess", "removeProcessGroup", "addProcessGroup"):
        try:
            getattr(clustercli.supervisor, step)(proc)
        except Exception:
            pass
    # Declared validators carry autostart=true, so addProcessGroup already
    # starts the node; startProcess would then raise ALREADY_STARTED.
    try:
        clustercli.supervisor.startProcess(proc)
    except Exception:
        pass


def _sender(w3, key, address):
    """Return send(to, value=1), firing from address and counting nonces here.

    The mempool inserts asynchronously, so pending still reports the old nonce
    and a burst left to fill_nonce collides. RPC errors are ignored.
    """
    gas_price = w3.eth.gas_price
    nonce = w3.eth.get_transaction_count(address)

    def send(to, value=1):
        nonlocal nonce
        tx = {"to": to, "value": value, "gasPrice": gas_price, "nonce": nonce}
        nonce += 1
        try:
            send_transaction(w3, tx, key=key, check=False)
        except Exception:
            pass

    return send


def _scan(log, start=0):
    """(text, missing-node panic, AppHash divergence) for the log after start.

    Both variants share one node log, scanning from 0 re-reports earlier variant's fault
    """
    if not log.exists():
        return "", None, None
    with log.open(errors="ignore") as fp:
        fp.seek(start)
        text = fp.read()

    def excerpt(needle):
        i = text.find(needle)
        return text[i : i + 400] if i != -1 else None

    return text, excerpt(MISSING_NODE_ERR), excerpt(APPHASH_ERR)


@pytest.mark.parametrize("blocksync", [False, True], ids=["gossip", "blocksync"])
def test_stale_pin_faults(mantra, blocksync):
    """A stale mempool cache reads a version pruning has deleted.

    Freezing the refresher pins the mempool to an IAVL version pruning then
    deletes. Each sender is read for the first time only after that, so the read
    has to reach disk, where the nodes are gone. An already-traversed key would
    still answer from the ImmutableTree whatever iavl-cache-size says, which is
    why the senders must be cold. Needs EVM_MEMPOOL_FREEZE_CTX_AFTER in evm.

    How node3 meets those txs decides where the fault lands, and how bad it is:

    gossip -- node3 is up, so each tx enters its pool and legacypool.validateTx
    reads the sender's nonce through the pinned statedb. That runs in the insert
    queue's goroutine, outside baseapp's recovery, so the panic takes the node
    down instead of failing one tx. No AppHash move: nothing was executing.

    blocksync -- node3 is down while they commit, so it meets them only inside a
    block. Where Remove still validates through the pin the read lands in
    deliverTx instead, and the recovered panic diverges node3's AppHash. Current
    main does not: shouldRemoveFromEVMPool reads reason.Error and no state.
    """
    n_senders = int(os.getenv("STALE_SENDERS", "40"))
    churn_blocks = int(os.getenv("STALE_CHURN_BLOCKS", "40"))
    deadline = time.time() + int(os.getenv("STALE_TIMEOUT", "900"))
    freeze_after = os.getenv("STALE_FREEZE_AFTER", "2")

    cli0 = mantra.cosmos_cli(0)
    w3 = mantra.w3
    base_dir = Path(mantra.base_dir).parent
    chain_dir = base_dir / mantra.config["chain_id"]
    clustercli = cluster.ClusterCLI(
        base_dir,
        cmd=mantra.config.get("cmd") or CMD,
        chain_id=mantra.config["chain_id"],
    )
    log = chain_dir / f"node{NODE}.log"
    log_start = log.stat().st_size if log.exists() else 0
    proc = f"{clustercli.chain_id}-node{NODE}"
    fund = _sender(w3, KEYS["community"], ADDRS["community"])

    # (1) Fund the senders while node3 follows, so they land in its pinned
    # version; later accounts just read back not-found.
    senders = [derive_new_account(n + 400) for n in range(n_senders)]
    for acct in senders:
        fund(acct.address, 10**17)
    wait_for_block(cli0, cli0.block_height() + 4)
    assert w3.eth.get_balance(senders[0].address) > 0, "sender funding did not land"
    funded_at = cli0.block_height()

    # (2) Freeze the pin. Restarting is what injects the env, and node3 comes
    # back above funded_at either way, so the senders stay inside the pin.
    if blocksync:
        clustercli.supervisor.stopProcess(proc)
    else:
        _restart_frozen(clustercli, chain_dir, freeze_after)
        wait_for_block(clustercli.cosmos_cli(NODE), funded_at + 4)

    # (3) Churn so pruning drops the pinned version, then have every sender
    # transact for the first time -- the read that has to reach disk.
    start = cli0.block_height()
    while cli0.block_height() < start + churn_blocks and time.time() < deadline:
        fund(ADDRS["signer2"])
        time.sleep(0.5)
    for acct in senders:
        _sender(w3, acct.key, acct.address)(ADDRS["signer2"])

    if blocksync:
        # Let them commit while node3 is down, so it meets them only in a block.
        wait_for_block(cli0, cli0.block_height() + 3)
        _restart_frozen(clustercli, chain_dir, freeze_after)
    print(f"\nnode{NODE} frozen after {freeze_after}, funded by {funded_at}")

    # (4) Watch for the fault, keeping the chain moving: a recovered panic
    # surfaces only at the next header comparison.
    panic_hit = apphash_hit = None
    grace = min(time.time() + int(os.getenv("STALE_GRACE", "180")), deadline)
    while time.time() < grace:
        time.sleep(2)
        _, panic, apphash = _scan(log, log_start)
        panic_hit, apphash_hit = panic_hit or panic, apphash_hit or apphash
        if apphash_hit or (panic_hit and not blocksync):
            break  # an execModeCheck fault cannot diverge; nothing to wait for
        fund(ADDRS["signer2"])

    text, panic, apphash = _scan(log, log_start)
    panic_hit, apphash_hit = panic_hit or panic, apphash_hit or apphash
    pins = sorted({int(m.split("=")[1]) for m in re.findall(r"ctx_height=\d+", text)})
    modes = re.findall(r"runTx\(0x[a-f0-9]+, (0x[0-9a-f]+)", text)
    print(f"pins seen: {pins}; panic exec modes: {modes} (0x0=CheckTx, 0x7=Finalize)")

    if panic_hit or apphash_hit:
        pytest.fail(
            "REPRODUCED -- stale pinned context\n\n"
            f"missing-node panic:\n{panic_hit}\n\nAppHash divergence:\n{apphash_hit}"
        )

    # Tell a real negative from a vacuous run; neither proves pruning passed
    # the pin, so a skip means "no fault seen", not "iavl was correct".
    assert pins, "vacuous: the pinned context was never read (freeze hook built in?)"
    assert max(pins) > funded_at, (
        f"vacuous: pin froze at {max(pins)} <= funding height {funded_at}, so the "
        "senders are absent from the pinned tree and reads return not-found"
    )
    pytest.skip(f"not reproduced: pin stuck at {max(pins)}, all reads resolved")

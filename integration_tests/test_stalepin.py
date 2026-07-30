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
    """Start node NODE with its latestCtx refresher frozen after n
    notifications, modelling the subscription drop seen in production.

    Scoped to one program so the validators keep refreshing. The pin is rebuilt
    on every start, so this only affects the run that follows.
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
    try:
        clustercli.supervisor.removeProcessGroup(proc)
    except Exception:
        pass
    # Declared validators carry autostart=true, so addProcessGroup already
    # starts the node; startProcess would then raise ALREADY_STARTED.
    clustercli.supervisor.addProcessGroup(proc)
    try:
        clustercli.supervisor.startProcess(proc)
    except Exception:
        pass


def _send(w3, gas_price, key, to, value=1):
    """Fire one tx, ignoring nonce collisions and transient RPC errors."""
    try:
        send_transaction(
            w3, {"to": to, "value": value, "gasPrice": gas_price}, key=key, check=False
        )
    except Exception:
        pass


def _find(text, needle, ctx=400):
    idx = text.find(needle)
    return text[idx : idx + ctx] if idx != -1 else None


def test_stale_pin_diverges_via_blocksync(mantra):
    """A stale mempool cache read during block sync diverges the AppHash.

    Freezing the refresher, as a dropped CometBFT subscription would, pins the
    mempool to an IAVL version pruning then deletes. Fails before the EndBlock
    fix, skips after. Needs EVM_MEMPOOL_FREEZE_CTX_AFTER in evm.

    node3 must meet each tx first inside a block: by gossip it panics in CheckTx,
    which is local to it and cannot move the AppHash.
    """
    n_senders = int(os.getenv("STALE_SENDERS", "40"))
    churn_blocks = int(os.getenv("STALE_CHURN_BLOCKS", "40"))
    deadline = time.time() + int(os.getenv("STALE_TIMEOUT", "900"))

    cli0 = mantra.cosmos_cli(0)
    w3 = mantra.w3
    gas_price = w3.eth.gas_price
    chain_dir = Path(mantra.base_dir).parent / mantra.config["chain_id"]
    clustercli = cluster.ClusterCLI(
        Path(mantra.base_dir).parent,
        cmd=mantra.config.get("cmd") or CMD,
        chain_id=mantra.config["chain_id"],
    )
    log = chain_dir / f"node{NODE}.log"

    # (1) Fund the senders while node3 follows, so they exist in its pinned
    # version; accounts created later just read back not-found.
    senders = [derive_new_account(n + 400) for n in range(n_senders)]
    for acct in senders:
        _send(w3, gas_price, KEYS["community"], acct.address, 10**17)
    wait_for_block(cli0, cli0.block_height() + 4)
    assert w3.eth.get_balance(senders[0].address) > 0, "sender funding did not land"
    funded_at = cli0.block_height()

    # (2) Take node3 down and build the backlog it will replay. Churn first, so
    # pruning drops the pinned version before node3 reaches the sender txs.
    clustercli.supervisor.stopProcess(f"{clustercli.chain_id}-node{NODE}")
    stopped_at = cli0.block_height()
    target = stopped_at + churn_blocks
    while cli0.block_height() < target and time.time() < deadline:
        _send(w3, gas_price, KEYS["community"], ADDRS["signer2"])
        time.sleep(0.5)

    # These commit while node3 is offline, so it only meets them in a block.
    for acct in senders:
        _send(w3, gas_price, acct.key, ADDRS["signer2"])
    wait_for_block(cli0, cli0.block_height() + 3)
    print(f"\nnode{NODE} down from {stopped_at}, chain now at {cli0.block_height()}")

    # (3) Restart frozen: the pin sticks at the restart height while sync races
    # past it and pruning deletes it.
    _restart_frozen(clustercli, chain_dir, os.getenv("STALE_FREEZE_AFTER", "2"))

    # (4) Wait out the catch-up, stopping early once the fault shows.
    panic_hit = apphash_hit = None
    while time.time() < deadline:
        time.sleep(2)
        text = log.read_text(errors="ignore") if log.exists() else ""
        panic_hit = panic_hit or _find(text, MISSING_NODE_ERR)
        apphash_hit = apphash_hit or _find(text, APPHASH_ERR)
        if apphash_hit:
            break
        try:
            if clustercli.cosmos_cli(NODE).block_height() >= cli0.block_height():
                # A recovered panic only surfaces once the next header is
                # compared, so keep the chain moving while one is pending.
                if panic_hit:
                    _send(w3, gas_price, KEYS["community"], ADDRS["signer2"])
                    continue
                break
        except Exception:
            pass  # node3 is down mid-panic; the log still tells us what happened

    text = log.read_text(errors="ignore") if log.exists() else ""
    pins = sorted({int(m.split("=")[1]) for m in re.findall(r"ctx_height=\d+", text)})
    modes = re.findall(r"runTx\(0x[a-f0-9]+, (0x[0-9a-f]+)", text)
    print(f"pins seen: {pins}; panic exec modes: {modes} (0x0=CheckTx, 0x7=Finalize)")

    if panic_hit or apphash_hit:
        pytest.fail(
            "REPRODUCED -- stale pin read during block sync\n\n"
            f"missing-node panic:\n{panic_hit}\n\nAppHash divergence:\n{apphash_hit}"
        )

    # Tell a real negative from a vacuous run; neither proves pruning passed the
    # pin, so a skip means "no fault seen", not "iavl was correct".
    assert pins, "vacuous: shouldRemoveFromEVMPool never ran (NoOpMempool?)"
    assert max(pins) > funded_at, (
        f"vacuous: pin froze at {max(pins)} <= funding height {funded_at}, so the "
        "senders are absent from the pinned tree and reads return not-found"
    )
    pytest.skip(f"not reproduced: pin stuck at {max(pins)}, all reads resolved")

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


def _freeze_ctx_after(chain_dir, chain_id, i, n):
    """Stop node i's latestCtx refresher after n notifications.

    Scoped to one supervisor program so the validators keep refreshing. n must
    exceed the senders' funding height, or they are not in the pinned tree.
    """
    ini_path = chain_dir / cluster.SUPERVISOR_CONFIG_FILE
    ini = configparser.RawConfigParser()
    ini.read(ini_path)
    section = f"program:{chain_id}-node{i}"
    assert ini.has_section(section), f"no {section} in {ini_path}"
    ini.set(section, "environment", f"EVM_MEMPOOL_FREEZE_CTX_AFTER={n}")
    with ini_path.open("w") as fp:
        ini.write(fp)


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


def test_stale_pinned_context_faults(mantra):
    """A stale mempool cache reads a pruned node and panics.

    Freezing the refresher, as a dropped CometBFT subscription would, leaves the
    mempool pinned to an IAVL version pruning then deletes. Fails before the
    EndBlock fix, skips after. Needs EVM_MEMPOOL_FREEZE_CTX_AFTER in evm.

    Miss any of these and the run is a silent false negative: the account must
    exist in the pinned version, be rewritten after it (orphaning its leaf for
    pruning), and be read for the first time only after that -- an ImmutableTree
    keeps traversed nodes in memory whatever iavl-cache-size says.
    """
    n_senders = int(os.getenv("STALE_SENDERS", "40"))
    churn_blocks = int(os.getenv("STALE_CHURN_BLOCKS", "40"))
    deadline = time.time() + int(os.getenv("STALE_TIMEOUT", "600"))

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
    proc = f"{clustercli.chain_id}-node{NODE}"

    # (1) Fund the senders, then restart the target node with its refresher
    # frozen. They must exist in whatever version the pin lands on: accounts
    # created later are absent from the pinned tree, so reads return not-found.
    senders = [derive_new_account(n + 300) for n in range(n_senders)]
    for acct in senders:
        _send(w3, gas_price, KEYS["community"], acct.address, 10**17)
    wait_for_block(cli0, cli0.block_height() + 4)
    assert w3.eth.get_balance(senders[0].address) > 0, "sender funding did not land"
    funded_at = cli0.block_height()

    # The refresher fires once per block, so n notifications pin roughly
    # version n; it must land above funded_at.
    clustercli.supervisor.stopProcess(proc)
    _freeze_ctx_after(
        chain_dir,
        clustercli.chain_id,
        NODE,
        os.getenv("STALE_FREEZE_AFTER", str(funded_at + 8)),
    )
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
    wait_for_block(clustercli.cosmos_cli(NODE), funded_at + 10)
    print(
        f"\nnode{NODE} at {clustercli.cosmos_cli(NODE).block_height()}, "
        f"funded by {funded_at}"
    )

    # (2) Orphan each sender's pinned-version leaf by paying it again -- this
    # rewrites the balance without the mempool reading the account.
    for acct in senders:
        _send(w3, gas_price, KEYS["community"], acct.address)

    # Advance past the pin so pruning deletes those orphans.
    target = cli0.block_height() + churn_blocks
    while cli0.block_height() < target and time.time() < deadline:
        _send(w3, gas_price, KEYS["community"], ADDRS["signer2"])
        time.sleep(0.5)

    # (3) Each sender transacts for the first time, so the ante handler reads its
    # balance through the stale pin and hits a deleted node.
    panic_hit = apphash_hit = None
    for acct in senders:
        if panic_hit or time.time() > deadline:
            break  # one fault is the whole result; no need to walk the rest
        _send(w3, gas_price, acct.key, ADDRS["signer2"])
        time.sleep(0.4)
        text = log.read_text(errors="ignore") if log.exists() else ""
        panic_hit = panic_hit or _find(text, MISSING_NODE_ERR)
        apphash_hit = _find(text, APPHASH_ERR)

    # Keep running briefly: a recovered panic leaves state divergent, and
    # CometBFT only reports that when the next block's header AppHash is
    # compared. Short once the panic is in hand -- an execModeCheck fault cannot
    # diverge the AppHash, so a long wait here is dead time.
    grace = time.time() + int(os.getenv("STALE_GRACE", "10" if panic_hit else "90"))
    while time.time() < grace and not apphash_hit:
        _send(w3, gas_price, KEYS["community"], ADDRS["signer2"])
        time.sleep(1)
        text = log.read_text(errors="ignore") if log.exists() else ""
        panic_hit = panic_hit or _find(text, MISSING_NODE_ERR)
        apphash_hit = _find(text, APPHASH_ERR)

    text = log.read_text(errors="ignore") if log.exists() else ""
    pins = sorted({int(m.split("=")[1]) for m in re.findall(r"ctx_height=\d+", text)})
    modes = re.findall(r"runTx\(0x[a-f0-9]+, (0x[0-9a-f]+)", text)
    print(f"pins seen: {pins}; panic exec modes: {modes} (0x0=CheckTx, 0x7=Finalize)")

    if panic_hit or apphash_hit:
        pytest.fail(
            "REPRODUCED -- stale pinned context\n\n"
            f"missing-node panic:\n{panic_hit}\n\nAppHash divergence:\n{apphash_hit}"
        )

    # Tell a real negative from a vacuous run. Note neither check proves pruning
    # passed the pin, so a skip means "no fault seen", not "iavl was correct".
    assert pins, "vacuous: shouldRemoveFromEVMPool never ran (NoOpMempool?)"
    assert max(pins) > funded_at, (
        f"vacuous: pin froze at {max(pins)} <= funding height {funded_at}, so the "
        "senders are absent from the pinned tree and reads return not-found"
    )
    pytest.skip(f"not reproduced: pin stuck at {max(pins)}, all reads resolved")

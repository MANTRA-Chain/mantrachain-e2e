import re
import subprocess
import time
from pathlib import Path

from pystarport.cluster import SUPERVISOR_CONFIG_FILE

from .utils import edit_ini_sections

CONFIGS_DIR = Path(__file__).parent / "configs"
V800_NIX = (CONFIGS_DIR / "mantrachaind-v8_0_0.nix").resolve()
V801_NIX = (CONFIGS_DIR / "mantrachaind-v8_0_1.nix").resolve()

APPHASH_PATTERNS = (
    "wrong Block.Header.AppHash",
    "wrong Block.Header.LastResultsHash",
    "BlockExecutor failed",
    "ApplyBlock failed",
    "invalid block time",
    "panic",
)


def nix_build_binary(nix_file: Path) -> str:
    out = subprocess.run(
        ["nix-build", str(nix_file), "--no-out-link"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    binary = Path(out) / "bin" / "mantrachaind"
    assert binary.exists(), f"mantrachaind not found at {binary}"
    return str(binary)


def override_node_binary(clustercli, i, binary):
    """Point node i's supervisor entry at a different binary."""
    chain_id = clustercli.chain_id
    ini_path = Path(clustercli.data_dir) / SUPERVISOR_CONFIG_FILE

    def cb(idx, _old):
        if idx == str(i):
            return {
                "command": (
                    f"{binary} start --home %(here)s/node{idx} --log_level info"
                ),
            }
        return {}

    edit_ini_sections(chain_id, ini_path, cb)
    clustercli.supervisor.reloadConfig()
    proc = f"{chain_id}-node{i}"
    try:
        clustercli.supervisor.removeProcessGroup(proc)
    except Exception:
        pass
    clustercli.supervisor.addProcessGroup(proc)


def scan_log_for_apphash(log_paths, deadline):
    """Return the first apphash/panic log line seen before deadline, else None."""
    pat = re.compile("|".join(re.escape(p) for p in APPHASH_PATTERNS))
    offsets = {p: 0 for p in log_paths}
    while time.time() < deadline:
        for p in log_paths:
            if not p.exists():
                continue
            with p.open("rb") as fp:
                fp.seek(offsets[p])
                chunk = fp.read().decode(errors="replace")
                offsets[p] = fp.tell()
            for line in chunk.splitlines():
                if pat.search(line):
                    return f"{p.name}: {line}"
        time.sleep(1)
    return None

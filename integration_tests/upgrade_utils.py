import json
import os
import shutil
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path

from pystarport.cluster import SUPERVISOR_CONFIG_FILE
from pystarport.utils import wait_for_block

from .network import setup_custom_mantra
from .utils import (
    CHAIN_ID,
    DEFAULT_DENOM,
    DEFAULT_GAS_PRICE,
    approve_proposal,
    edit_ini_sections,
)


def do_upgrade(c, plan_name, target):
    print(f"upgrade {plan_name} height: {target}")
    cli = c.cosmos_cli()
    rsp = cli.software_upgrade(
        "community",
        {
            "name": plan_name,
            "title": "upgrade test",
            "note": "ditto",
            "upgrade-height": target,
            "summary": "summary",
            "deposit": f"1{DEFAULT_DENOM}",
        },
        gas=300000,
        gas_prices=DEFAULT_GAS_PRICE,
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    approve_proposal(c, rsp["events"])

    # update cli chain binary
    c.chain_binary = (
        Path(c.chain_binary).parent.parent.parent / f"{plan_name}/bin/mantrachaind"
    )
    # block should pass the target height
    wait_for_block(c.cosmos_cli(), target + 1)
    return c.cosmos_cli()


def post_init(path, base_port, config, genesis):
    """
    prepare cosmovisor for each node
    """
    data = path / CHAIN_ID
    cfg = json.loads((data / "config.json").read_text())
    for i, _ in enumerate(cfg["validators"]):
        cosmovisor = data / f"node{i}/cosmovisor"
        cosmovisor.mkdir()
        (cosmovisor / "upgrades").symlink_to("../../../upgrades")
        (cosmovisor / "genesis").symlink_to(f"./upgrades/{genesis}")

    edit_ini_sections(
        CHAIN_ID,
        data / SUPERVISOR_CONFIG_FILE,
        lambda i, _: {
            "command": f"cosmovisor run start --home %(here)s/node{i}",
            "environment": (
                "DAEMON_NAME=mantrachaind,"
                "DAEMON_SHUTDOWN_GRACE=1m,"
                "UNSAFE_SKIP_BACKUP=true,"
                f"DAEMON_HOME=%(here)s/node{i}"
            ),
        },
    )


def build_upgrade_package(upgrades_dir):
    "nix-build the upgrade binaries into a writable `upgrades_dir`."
    output = "./result"
    nix_file = Path(__file__).parent / "configs/upgrade-test-package.nix"
    cmd = ["nix-build", nix_file, "-o", output]
    use_lite_mode = os.environ.get("NIX_LITE_MODE", "").lower() == "true"
    cmd += ["--arg", "useLiteMode", str(use_lite_mode).lower()]
    print(f"build {'lite' if use_lite_mode else 'full'} mode")
    print(*cmd)
    subprocess.run(cmd, check=True)
    # copy the content so the new directory is writable.
    shutil.copytree(output, upgrades_dir)
    mod = stat.S_IRWXU
    upgrades_dir.chmod(mod)
    for d in upgrades_dir.iterdir():
        d.chmod(mod)


def setup_mantra_upgrade(tmp_path_factory, chain, port):
    path = tmp_path_factory.mktemp("upgrade")
    upgrades = path / "upgrades"
    build_upgrade_package(upgrades)
    # init with genesis binary
    with contextmanager(setup_custom_mantra)(
        path,
        port,
        Path(__file__).parent / "configs/cosmovisor.jsonnet",
        post_init=post_init,
        chain_binary=str(upgrades / "genesis/bin/mantrachaind"),
        genesis="genesis",
        chain=chain,
    ) as mantra:
        yield mantra
    remove_upgrades(upgrades)


def remove_upgrades(upgrades):
    "Delete the copied upgrade binaries, whose directories nix left read-only."
    for root, _, _ in os.walk(upgrades):
        os.chmod(root, 0o755)
    shutil.rmtree(upgrades)

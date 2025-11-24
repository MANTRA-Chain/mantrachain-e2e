import json
import os
import shutil
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path

import tomlkit
from pystarport import ports
from pystarport.cluster import SUPERVISOR_CONFIG_FILE
from pystarport.utils import wait_for_block, wait_for_port

from .network import setup_custom_mantra
from .utils import (
    DEFAULT_DENOM,
    DEFAULT_GAS_AMT,
    EVM_CHAIN_ID,
    approve_proposal,
    bech32_to_eth,
    edit_ini_sections,
    send_transaction,
)

LEGACY_DENOM = "uom"
LEGACY_EXTENDED_DENOM = "aom"


def do_upgrade(c, plan_name, target, denom=DEFAULT_DENOM, min_deposit=1):
    print(f"upgrade {plan_name} height: {target}")
    cli = c.cosmos_cli()
    base_port = c.base_port(0)
    rsp = {}
    gas_prices = f"{80 * DEFAULT_GAS_AMT}{denom}"

    rsp = cli.software_upgrade(
        "community",
        {
            "name": plan_name,
            "title": "upgrade test",
            "note": "ditto",
            "upgrade-height": target,
            "summary": "summary",
            "deposit": f"{min_deposit}{denom}",
        },
        gas=300000,
        gas_prices=gas_prices,
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    approve_proposal(c, rsp["events"], gas_prices=gas_prices)

    # update cli chain binary
    c.chain_binary = (
        Path(c.chain_binary).parent.parent.parent / f"{plan_name}/bin/mantrachaind"
    )
    # block should pass the target height
    wait_for_block(c.cosmos_cli(), target + 2, timeout=480)
    wait_for_port(ports.rpc_port(base_port))
    return c.cosmos_cli()


def init_cosmovisor(home, genesis):
    """
    build and setup cosmovisor directory structure in each node's home directory
    """
    cosmovisor = home / "cosmovisor"
    cosmovisor.mkdir()
    (cosmovisor / "upgrades").symlink_to("../../../upgrades")
    (cosmovisor / "genesis").symlink_to(f"./upgrades/{genesis}")


def post_init(path, base_port, config, genesis):
    """
    prepare cosmovisor for each node
    """
    chain_id = "mantra-canary-net-1"
    data = path / chain_id
    cfg = json.loads((data / "config.json").read_text())
    for i, _ in enumerate(cfg["validators"]):
        home = data / f"node{i}"
        init_cosmovisor(home, genesis)

    edit_ini_sections(
        chain_id,
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


def build_upgrade_package(upgrades_dir, nix_file, output="./result"):
    cmd = [
        "nix-build",
        nix_file,
        "-o",
        output,
    ]
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
    return cmd


def setup_mantra_upgrade(
    tmp_path_factory, nix_name, cfg_name, genesis, chain, port=26200
):
    path = tmp_path_factory.mktemp("upgrade")
    configdir = Path(__file__).parent
    upgrades = path / "upgrades"
    build_upgrade_package(upgrades, configdir / f"configs/{nix_name}.nix")
    # init with genesis binary
    with contextmanager(setup_custom_mantra)(
        path,
        port,
        configdir / f"configs/{cfg_name}.jsonnet",
        post_init=post_init,
        chain_binary=str(upgrades / f"{genesis}/bin/mantrachaind"),
        genesis=genesis,
        chain=chain,
    ) as mantra:
        yield mantra


def make_writable_recursive(path):
    for root, dirs, files in os.walk(path):
        for d in dirs:
            os.chmod(os.path.join(root, d), 0o777)
        for f in files:
            os.chmod(os.path.join(root, f), 0o666)
        os.chmod(root, 0o777)


def handle_remove_readonly(func, path, exc):
    os.chmod(path, 0o777)
    func(path)


def cleanup_upgrades_folder(data_dir):
    upgrades_path = Path(data_dir / "../../upgrades")
    if upgrades_path.exists():
        for item in upgrades_path.iterdir():
            try:
                if item.is_dir():
                    make_writable_recursive(str(item))
                    shutil.rmtree(str(item), onerror=handle_remove_readonly)
                else:
                    item.chmod(0o666)
                    item.unlink()
            except Exception as e:
                print(f"Failed to remove {item}: {e}")


def check_basic_eth_tx(w3, contract, from_acc, to, msg):
    tx = contract.functions.setGreeting(msg).build_transaction()
    receipt = send_transaction(w3, tx, key=from_acc.key)
    assert receipt.status == 1
    assert contract.caller.greet() == msg
    # check basic tx works
    receipt = send_transaction(
        w3,
        {
            "from": from_acc.address,
            "to": bech32_to_eth(to),
            "value": 1000,
            "gas": 21000,
            "maxFeePerGas": 10000000000000,
            "maxPriorityFeePerGas": 10000,
        },
        key=from_acc.key,
    )
    assert receipt.status == 1


def patch_app_evm_chain_ids(c):
    for i in range(3):
        path = c.cosmos_cli(i=i).data_dir / "config/app.toml"
        cfg = tomlkit.parse(path.read_text())
        cfg["evm"] = {
            "evm-chain-id": EVM_CHAIN_ID,
        }
        path.write_text(tomlkit.dumps(cfg))

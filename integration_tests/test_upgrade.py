import json
import shutil
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest
from pystarport import ports
from pystarport.cluster import SUPERVISOR_CONFIG_FILE

from .network import Mantra, setup_custom_mantra
from .utils import (
    CONTRACTS,
    DEFAULT_FEE,
    approve_proposal,
    assert_transfer,
    bech32_to_eth,
    deploy_contract,
    derive_new_account,
    edit_ini_sections,
    eth_to_bech32,
    get_balance,
    send_transaction,
    wait_for_block,
    wait_for_new_blocks,
    wait_for_port,
)

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def custom_mantra(tmp_path_factory):
    yield from setup_mantra_test(tmp_path_factory)


def init_cosmovisor(home):
    """
    build and setup cosmovisor directory structure in each node's home directory
    """
    cosmovisor = home / "cosmovisor"
    cosmovisor.mkdir()
    (cosmovisor / "upgrades").symlink_to("../../../upgrades")
    (cosmovisor / "genesis").symlink_to("./upgrades/genesis")


def post_init(path, base_port, config):
    """
    prepare cosmovisor for each node
    """
    chain_id = "mantra-canary-net-1"
    data = path / chain_id
    cfg = json.loads((data / "config.json").read_text())
    for i, _ in enumerate(cfg["validators"]):
        home = data / f"node{i}"
        init_cosmovisor(home)

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


def setup_mantra_test(tmp_path_factory):
    path = tmp_path_factory.mktemp("upgrade")
    port = 26200
    nix_name = "upgrade-test-package"
    cfg_name = "cosmovisor"
    configdir = Path(__file__).parent
    cmd = [
        "nix-build",
        configdir / f"configs/{nix_name}.nix",
    ]
    print(*cmd)
    subprocess.run(cmd, check=True)

    # copy the content so the new directory is writable.
    upgrades = path / "upgrades"
    shutil.copytree("./result", upgrades)
    mod = stat.S_IRWXU
    upgrades.chmod(mod)
    for d in upgrades.iterdir():
        d.chmod(mod)

    # init with genesis binary
    with contextmanager(setup_custom_mantra)(
        path,
        port,
        configdir / f"configs/{cfg_name}.jsonnet",
        post_init=post_init,
        chain_binary=str(upgrades / "genesis/bin/mantrachaind"),
    ) as mantra:
        yield mantra


def exec(c):
    """
    - propose an upgrade and pass it
    - wait for it to happen
    - it should work transparently
    """
    cli = c.cosmos_cli()
    base_port = c.base_port(0)
    community = "community"

    c.supervisorctl(
        "start",
        "mantra-canary-net-1-node0",
        "mantra-canary-net-1-node1",
        "mantra-canary-net-1-node2",
    )
    wait_for_new_blocks(cli, 1)

    def do_upgrade(plan_name, target):
        print(f"upgrade {plan_name} height: {target}")
        rsp = cli.software_upgrade(
            community,
            {
                "name": plan_name,
                "title": "upgrade test",
                "note": "ditto",
                "upgrade-height": target,
                "summary": "summary",
                "deposit": "1uom",
            },
            gas=300000,
            gas_prices="0.8uom",
        )
        assert rsp["code"] == 0, rsp["raw_log"]
        approve_proposal(c, rsp["events"])

        # update cli chain binary
        c.chain_binary = (
            Path(c.chain_binary).parent.parent.parent / f"{plan_name}/bin/mantrachaind"
        )
        # block should pass the target height
        wait_for_block(c.cosmos_cli(), target + 2, timeout=480)
        wait_for_port(ports.rpc_port(base_port))
        return c.cosmos_cli()

    height = cli.block_height()
    target_height = height + 15

    cli = do_upgrade("v5", target_height)
    addr_a = cli.address(community)
    acc_b = derive_new_account(100)
    addr_b = eth_to_bech32(acc_b.address)

    wait_for_port(ports.evmrpc_port(c.base_port(0)))
    balance = get_balance(cli, community)
    assert_transfer(cli, addr_a, addr_b, amt=balance - DEFAULT_FEE)
    # check set contract tx works
    contract = deploy_contract(c.w3, CONTRACTS["Greeter"], key=acc_b.key)
    assert "Hello" == contract.caller.greet()
    tx = contract.functions.setGreeting("world").build_transaction()
    receipt = send_transaction(c.w3, tx, key=acc_b.key)
    assert receipt.status == 1
    # check basic tx works
    receipt = send_transaction(
        c.w3,
        {
            "from": acc_b.address,
            "to": bech32_to_eth(addr_a),
            "value": 1000,
            "gas": 21000,
            "maxFeePerGas": 10000000000000,
            "maxPriorityFeePerGas": 10000,
        },
        key=acc_b.key,
    )
    assert receipt.status == 1
    wait_for_new_blocks(cli, 3)


def test_cosmovisor_upgrade(custom_mantra: Mantra):
    exec(custom_mantra)

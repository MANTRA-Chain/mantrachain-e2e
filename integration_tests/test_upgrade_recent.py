import json
import shutil
import stat
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from eth_contract.erc20 import ERC20
from pystarport import ports
from pystarport.cluster import SUPERVISOR_CONFIG_FILE

from .network import Mantra, setup_custom_mantra
from .utils import (
    approve_proposal,
    assert_create_tokenfactory_denom,
    assert_mint_tokenfactory_denom,
    bech32_to_eth,
    denom_to_erc20_address,
    edit_ini_sections,
    wait_for_block,
    wait_for_new_blocks,
    wait_for_port,
)

pytestmark = pytest.mark.asyncio


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
    port = 26600
    nix_name = "upgrade-test-package-recent"
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
        configdir / "configs/cosmovisor_recent.jsonnet",
        post_init=post_init,
        chain_binary=str(upgrades / "genesis/bin/mantrachaind"),
    ) as mantra:
        yield mantra


async def exec(c):
    """
    - propose an upgrade and pass it
    - wait for it to happen
    - it should work transparently
    """
    cli = c.cosmos_cli()
    base_port = c.base_port(0)
    community = "community"
    gas = 300000

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
            gas=gas,
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
    addr_a = cli.address(community)
    signer1 = bech32_to_eth(addr_a)
    subdenom = f"admin{time.time()}"
    denom = assert_create_tokenfactory_denom(
        cli, subdenom, is_legacy=True, _from=addr_a, gas=620000
    )
    tf_erc20_addr = denom_to_erc20_address(denom)
    tf_amt = 10**6
    w3 = c.async_w3
    signer1_balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    balance = cli.balance(addr_a, denom)
    balance = assert_mint_tokenfactory_denom(cli, denom, tf_amt, _from=addr_a, gas=gas)
    signer1_balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    total = await ERC20.fns.totalSupply().call(w3, to=tf_erc20_addr)
    print("mm-signer1_balance_eth0", signer1_balance_eth, total, balance)
    assert total == balance == signer1_balance_eth == tf_amt
    cli = do_upgrade("v5.0.0-rc4", target_height)
    signer1_balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    total = await ERC20.fns.totalSupply().call(w3, to=tf_erc20_addr)
    balance = cli.balance(addr_a, denom)
    print("mm-signer1_balance_eth1", signer1_balance_eth, total, balance)
    # mm-signer1_balance_eth1 0 0 1000000
    # miss migrate for dynamic precompiles
    assert total == signer1_balance_eth == 0
    assert balance == tf_amt

    height = cli.block_height()
    target_height = height + 15
    cli = do_upgrade("v5.0.0-rc5", target_height)
    signer1_balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=tf_erc20_addr)
    total = await ERC20.fns.totalSupply().call(w3, to=tf_erc20_addr)
    balance = cli.balance(addr_a, denom)
    assert total == balance == signer1_balance_eth == tf_amt
    print("mm-signer1_balance_eth2", signer1_balance_eth, total, balance)

    c.supervisorctl("stop", "all")
    state = cli.export()["app_state"]
    assert state["erc20"]["native_precompiles"] == ["0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"]


async def test_cosmovisor_upgrade(custom_mantra: Mantra):
    await exec(custom_mantra)

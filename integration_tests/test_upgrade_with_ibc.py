import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import tomlkit

from .ibc_utils import (
    assert_ibc_transfer_flow,
    prepare_network,
)
from .network import Mantra
from .upgrade_utils import LEGACY_DENOM, cleanup_upgrades_folder, do_upgrade, post_init
from .utils import (
    CMD,
    DEFAULT_DENOM,
    DEFAULT_GAS_AMT,
    SCALE_FACTOR,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.skipped]


@pytest.fixture(scope="module")
def custom_mantra(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    nix_name = "upgrade-test-package-ibc"
    configdir = Path(__file__).parent
    name = "cosmovisor_with_ibc"
    path = tmp_path_factory.mktemp(name)
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

    binary = str(upgrades / f"genesis/bin/{CMD}")
    yield from prepare_network(
        path,
        name,
        chain=chain,
        b_chain="evm-canary-net-1",
        cmd="evmd",
        post_init=post_init,
        chain_binary=f"evmd,{binary}",
        genesis="genesis",
    )


async def exec(c, tmp_path):
    cli = c.ibc1.cosmos_cli()

    def upgrade():
        nonlocal cli
        target_height = cli.block_height() + 15
        cli = do_upgrade(c.ibc1, "v7.0.0-rc0", target_height, denom=LEGACY_DENOM)

        c.ibc1.supervisorctl("stop", "relayer-demo")
        rly_cfg = c.hermes.configpath
        cfg = tomlkit.parse(rly_cfg.read_text())
        cfg["chains"][1]["gas_price"] = {
            "denom": DEFAULT_DENOM,
            "price": DEFAULT_GAS_AMT,
        }
        rly_cfg.write_text(tomlkit.dumps(cfg))
        c.ibc1.supervisorctl("start", "relayer-demo")

    await assert_ibc_transfer_flow(
        c,
        denom=LEGACY_DENOM,
        upgrade_cb=upgrade,
    )

    target_height = cli.block_height() + 15
    cli = do_upgrade(c.ibc1, "v7.0.0-rc1", target_height, min_deposit=1 * SCALE_FACTOR)


async def test_cosmovisor_upgrade(custom_mantra: Mantra, tmp_path):
    await exec(custom_mantra, tmp_path)
    cleanup_upgrades_folder(custom_mantra.ibc1.cosmos_cli().data_dir)

from pathlib import Path

import pytest
import tomlkit

from .ibc_utils import (
    assert_ibc_transfer_flow,
    prepare_network,
)
from .network import Mantra
from .upgrade_utils import (
    LEGACY_DENOM,
    build_upgrade_package,
    cleanup_upgrades_folder,
    do_upgrade,
    post_init,
)
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
    name = "cosmovisor_with_ibc"
    path = tmp_path_factory.mktemp(name)
    configdir = Path(__file__).parent
    upgrades = path / "upgrades"
    nix_name = "upgrade-test-package-ibc"
    build_upgrade_package(upgrades, configdir / f"configs/{nix_name}.nix")
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


async def exec(c):
    cli = c.ibc1.cosmos_cli()

    def upgrade():
        nonlocal cli
        target_height = cli.block_height() + 15
        cli = do_upgrade(c.ibc1, "v7.0.0-rc2", target_height, denom=LEGACY_DENOM)

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
    cli = do_upgrade(c.ibc1, "v7.0.0-rc3", target_height, min_deposit=1 * SCALE_FACTOR)


async def test_cosmovisor_upgrade(custom_mantra: Mantra):
    await exec(custom_mantra)
    cleanup_upgrades_folder(custom_mantra.ibc1.cosmos_cli().data_dir)

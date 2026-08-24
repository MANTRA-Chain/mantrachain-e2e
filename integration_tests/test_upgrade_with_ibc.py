from pathlib import Path

import pytest

from .ibc_utils import (
    assert_ibc_transfer_flow,
    prepare_network,
)
from .network import Mantra
from .upgrade_utils import (
    build_upgrade_package,
    cleanup_upgrades_folder,
    do_upgrade,
    post_init,
)
from .utils import (
    CMD,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.skipped]

WAIT_HEIGHT = 12


@pytest.fixture(scope="module")
def custom_mantra(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    name = "cosmovisor_with_ibc"
    path = tmp_path_factory.mktemp(name)
    configdir = Path(__file__).parent
    upgrades = path / "upgrades"
    nix_name = "upgrade-test-package"
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
        """Upgrade mid-flow, so the transfers back exercise a migrated chain."""
        nonlocal cli
        cli = do_upgrade(c.ibc1, "v8.2.0", cli.block_height() + WAIT_HEIGHT)

    await assert_ibc_transfer_flow(c, upgrade_cb=upgrade)
    cli = do_upgrade(c.ibc1, "v8.3.0", cli.block_height() + WAIT_HEIGHT)
    cli = do_upgrade(c.ibc1, "v8.4.0", cli.block_height() + WAIT_HEIGHT)


async def test_cosmovisor_upgrade(custom_mantra: Mantra):
    await exec(custom_mantra)
    cleanup_upgrades_folder(custom_mantra.ibc1.cosmos_cli().data_dir)

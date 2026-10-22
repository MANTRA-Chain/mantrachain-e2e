import pytest

from .ibc_utils import (
    assert_ibc_transfer_flow,
    prepare_network,
)
from .network import Mantra
from .upgrade_utils import (
    build_upgrade_package,
    do_upgrade,
    post_init,
    remove_upgrades,
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
    upgrades = path / "upgrades"
    build_upgrade_package(upgrades)
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
    remove_upgrades(upgrades)


async def test_cosmovisor_upgrade(custom_mantra: Mantra):
    c = custom_mantra

    def upgrade(plan):
        do_upgrade(c.ibc1, plan, c.ibc1.cosmos_cli().block_height() + WAIT_HEIGHT)

    # upgrade mid-flow, so the transfers back exercise a migrated chain
    await assert_ibc_transfer_flow(c, upgrade_cb=lambda: upgrade("v8.4.0"))
    upgrade("v8.5.0-pre.1")
    upgrade("v8.7.0-pre.1")

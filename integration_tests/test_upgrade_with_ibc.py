from pathlib import Path

import pytest
import requests

from .ibc_utils import (
    add_rate_limit,
    api_url,
    assert_ibc_transfer_flow,
    prepare_network,
    query_legacy_rate_limits,
    query_rate_limit,
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
    DEFAULT_GAS_PRICE,
    ensure_comet_mempool_app,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.skipped]

WAIT_HEIGHT = 12
MAX_PERCENT_SEND = 30
MAX_PERCENT_RECV = 50


def add_legacy_rate_limit(chain, tmp_path):
    "add a rate limit on the v8.4 binary, via the legacy ratelimit.v1 msg"
    add_rate_limit(
        chain,
        tmp_path,
        max_percent_send=MAX_PERCENT_SEND,
        max_percent_recv=MAX_PERCENT_RECV,
        legacy=True,
        gas_prices=DEFAULT_GAS_PRICE,
    )
    rsp = query_legacy_rate_limits(chain).json()
    assert rsp.get("rate_limits"), rsp


def assert_rate_limit_migrated(chain):
    "the v8.4 rate limit survives the swap to the ibc-go v11 module"
    limit = query_rate_limit(chain)
    assert limit["quota"]["max_percent_send"] == str(MAX_PERCENT_SEND), limit
    assert limit["quota"]["max_percent_recv"] == str(MAX_PERCENT_RECV), limit
    # the upgrade handler replays Migrate1to2 to clear legacy pending packet
    # markers, landing the module on the ibc-go consensus version
    path = "/cosmos/upgrade/v1beta1/module_versions?module_name=ratelimit"
    rsp = requests.get(api_url(chain, path)).json()
    assert rsp.get("module_versions") == [{"name": "ratelimit", "version": "2"}], rsp


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


async def run_upgrades(c, tmp_path):
    cli = c.ibc1.cosmos_cli()

    def upgrade():
        """Upgrade mid-flow, so the transfers back exercise a migrated chain."""
        nonlocal cli
        cli = do_upgrade(c.ibc1, "v8.4.0", cli.block_height() + WAIT_HEIGHT)

    await assert_ibc_transfer_flow(c, upgrade_cb=upgrade)
    add_legacy_rate_limit(c.ibc1, tmp_path)
    ensure_comet_mempool_app(c.ibc1.base_dir)
    cli = do_upgrade(c.ibc1, "v8.5.0", cli.block_height() + WAIT_HEIGHT)
    assert_rate_limit_migrated(c.ibc1)

    # v8.5.0 rewires the whole transfer stack on ibc-go v11, so run the flow
    # again on the upgraded chain. The no-op callback keeps the dynamic-fee
    # assertion skipped; the channel-open txs it reads predate this binary.
    await assert_ibc_transfer_flow(c, upgrade_cb=lambda: None)


async def test_cosmovisor_upgrade(custom_mantra: Mantra, tmp_path):
    await run_upgrades(custom_mantra, tmp_path)
    cleanup_upgrades_folder(custom_mantra.ibc1.cosmos_cli().data_dir)

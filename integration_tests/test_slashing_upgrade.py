"""End-to-end repair test for the v8.1.0 silent-slash migration."""

import pytest
from pystarport.utils import wait_for_new_blocks

from .network import Mantra
from .slashing_utils import (
    JAILED_NODE_NAME,
    jail_target_and_assert_slashed,
    setup_dust_delegation,
)
from .upgrade_utils import (
    LEGACY_DENOM,
    cleanup_upgrades_folder,
    do_upgrade,
    setup_mantra_upgrade,
)
from .utils import SCALE_FACTOR

pytestmark = [pytest.mark.skipped]

WAIT_HEIGHT = 30


@pytest.fixture(scope="module")
def custom_mantra(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    yield from setup_mantra_upgrade(
        tmp_path_factory,
        "upgrade-test-package-recent",
        "cosmovisor_recent_slashing",
        "genesis",
        chain=chain,
        port=27210,
    )


def test_silent_slash_repair(custom_mantra: Mantra):
    c = custom_mantra
    cli = c.cosmos_cli()

    cli = do_upgrade(c, "v7.0.0", cli.block_height() + WAIT_HEIGHT, denom=LEGACY_DENOM)
    cli = do_upgrade(c, "v8.0.0", cli.block_height() + WAIT_HEIGHT, scale=SCALE_FACTOR)

    target_val, signer1 = setup_dust_delegation(c, cli)
    jail_target_and_assert_slashed(c, cli, target_val)

    with pytest.raises(AssertionError, match="calculated final stake"):
        cli.distribution_rewards(signer1)

    # restart node so approve_proposal can vote from it; jailed state persists.
    c.supervisorctl("start", JAILED_NODE_NAME)
    wait_for_new_blocks(cli, 2, timeout=60)

    cli = do_upgrade(c, "v8.1.0", cli.block_height() + WAIT_HEIGHT, scale=SCALE_FACTOR)

    # fixSilentlySkippedSlashes clamped the orphaned starting info
    cli.distribution_rewards(signer1)

    cleanup_upgrades_folder(cli.data_dir)

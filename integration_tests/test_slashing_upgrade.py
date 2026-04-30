"""End-to-end repair test for the v8.1.0 silent-slash migration."""

import time

import pytest
from pystarport.utils import wait_for_new_blocks

from .network import Mantra
from .upgrade_utils import (
    LEGACY_DENOM,
    cleanup_upgrades_folder,
    do_upgrade,
    setup_mantra_upgrade,
)
from .utils import SCALE_FACTOR

pytestmark = [pytest.mark.skipped]

JAILED_NODE_INDEX = 2
CHAIN_ID = "mantra-canary-net-1"
JAILED_NODE = f"{CHAIN_ID}-node{JAILED_NODE_INDEX}"
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


def _expect_rewards_query_panics(cli, signer1):
    with pytest.raises(AssertionError) as excinfo:
        cli.distribution_rewards(signer1)
    assert "calculated final stake" in str(excinfo.value)


def test_silent_slash_repair(custom_mantra: Mantra):
    c = custom_mantra
    cli = c.cosmos_cli()

    # walk to v8.0.0 (the buggy binary). v8.x upgrades need scale=SCALE_FACTOR
    # so the gas_price scales to amantra units and the tx clears the global
    # min fee (3.2 MANTRA) without blowing past block max_gas.
    cli = do_upgrade(c, "v7.0.0", cli.block_height() + WAIT_HEIGHT, denom=LEGACY_DENOM)
    cli = do_upgrade(c, "v8.0.0", cli.block_height() + WAIT_HEIGHT, scale=SCALE_FACTOR)

    target_cli = c.cosmos_cli(JAILED_NODE_INDEX)
    target_val = target_cli.address("validator", "val")

    name = "signer1"
    signer1 = cli.address(name)
    # delegate < PowerReduction so consensus power is unchanged
    # (otherwise stopping target would drop alive VP below 2/3).
    rsp = cli.delegate_amount(target_val, "1amantra", _from=name, gas=400_000)
    assert rsp["code"] == 0, rsp["raw_log"]
    wait_for_new_blocks(cli, 2, timeout=60)
    cli.distribution_rewards(signer1)

    tokens_bf = int(cli.validator(target_val)["tokens"])

    c.supervisorctl("stop", JAILED_NODE)

    # window=30, min=0.5 -> jail after 16 missed
    jailed = False
    deadline = time.time() + 240
    while time.time() < deadline:
        try:
            wait_for_new_blocks(cli, 2, timeout=60)
        except TimeoutError:
            pytest.fail(
                f"chain stopped producing blocks at height {cli.block_height()} "
                "after stopping validator"
            )
        if cli.validator(target_val).get("jailed"):
            jailed = True
            break
    assert jailed, "validator was not jailed within the wait window"

    tokens_af = int(cli.validator(target_val)["tokens"])
    assert (
        tokens_af < tokens_bf
    ), f"validator tokens should be reduced by the slash: {tokens_bf} -> {tokens_af}"

    # bug present: slash event missing -> rewards query panics
    _expect_rewards_query_panics(cli, signer1)

    # restart node so approve_proposal can vote from it; jailed state persists.
    c.supervisorctl("start", JAILED_NODE)
    wait_for_new_blocks(cli, 2, timeout=60)

    cli = do_upgrade(c, "v8.1.0", cli.block_height() + WAIT_HEIGHT, scale=SCALE_FACTOR)

    # fixSilentlySkippedSlashes clamped the orphaned starting info
    cli.distribution_rewards(signer1)

    cleanup_upgrades_folder(cli.data_dir)

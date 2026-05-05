import json
import time
from decimal import Decimal

import pytest
from pystarport.utils import wait_for_new_blocks

from .network import Mantra
from .slashing_utils import (
    JAILED_NODE_INDEX,
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
JAIL_DURATION_S = 65  # downtime_jail_duration is 60s in the fixture; +5s slack.


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


def _slashes(cli, validator, start_h=1, end_h=10**12):
    res = json.loads(
        cli.raw(
            "q",
            "distribution",
            "slashes",
            validator,
            str(start_h),
            str(end_h),
            **cli.get_base_kwargs(),
        )
    )
    return res.get("slashes") or []


def test_silent_slash_repair(custom_mantra: Mantra):
    """v7 jail records a ValidatorSlashEvent; v8 jail is silent. v8.1.1 must
    keep the recorded factor (no over-clamp) and clamp the silent residue."""
    c = custom_mantra
    cli = c.cosmos_cli()
    cli = do_upgrade(c, "v7.0.0", cli.block_height() + WAIT_HEIGHT, denom=LEGACY_DENOM)

    # signer1 delegates BEFORE v7 jail → mixed case (mirrors mainnet val1/val2):
    # info.Height < v7 event height, iteration finds the recorded event,
    # hasEvents=true → ratio path.
    target_val, signer1 = setup_dust_delegation(c, cli, signer_name="signer1")
    jail_target_and_assert_slashed(c, cli, target_val)
    v7_slashes = _slashes(cli, target_val)
    assert len(v7_slashes) == 1, f"got {v7_slashes}"

    # unjail so v8 jail can fire again.
    c.supervisorctl("start", JAILED_NODE_NAME)
    wait_for_new_blocks(cli, 2, timeout=60)
    time.sleep(JAIL_DURATION_S)
    rsp = c.cosmos_cli(JAILED_NODE_INDEX).unjail(
        "validator", gas=400_000, gas_prices="100000000000amantra"
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    wait_for_new_blocks(cli, 5, timeout=120)

    # signer2 delegates AFTER v7 jail → silent-only case (mirrors mainnet val3):
    # info.Height > v7 event height, iteration finds nothing, hasEvents=false
    # → else branch (newStake = currentStake exact).
    _, signer2 = setup_dust_delegation(c, cli, signer_name="signer2")

    # v8 jail → silent slash (no new event).
    cli = do_upgrade(c, "v8.0.0", cli.block_height() + WAIT_HEIGHT, scale=SCALE_FACTOR)
    jail_target_and_assert_slashed(c, cli, target_val)
    assert len(_slashes(cli, target_val)) == len(v7_slashes)
    with pytest.raises(AssertionError, match="calculated final stake"):
        cli.distribution_rewards(signer1)
    with pytest.raises(AssertionError, match="calculated final stake"):
        cli.distribution_rewards(signer2)

    c.supervisorctl("start", JAILED_NODE_NAME)
    wait_for_new_blocks(cli, 2, timeout=60)

    # v8.1.1 clamp.
    cli = do_upgrade(c, "v8.1.1", cli.block_height() + WAIT_HEIGHT, scale=SCALE_FACTOR)
    cli.distribution_rewards(signer1)
    cli.distribution_rewards(signer2)
    assert _slashes(cli, target_val) == v7_slashes

    # Compute currentStake as full-precision LegacyDec (val.tokens × shares /
    # val.delegator_shares). The integer balance.amount truncates to 0 for our
    # 1 amantra dust delegation.
    def _full_cur(d):
        v = cli.validator(target_val)
        de = cli.delegation(d, target_val)["delegation"]
        return (
            Decimal(v["tokens"])
            * Decimal(de["shares"])
            / Decimal(v["delegator_shares"])
        )

    cur1 = _full_cur(signer1)
    cur2 = _full_cur(signer2)

    c.supervisorctl("stop", JAILED_NODE_NAME)
    distribution = c.cosmos_cli(JAILED_NODE_INDEX).export(
        modules_to_export="distribution"
    )["app_state"]["distribution"]
    c.supervisorctl("start", JAILED_NODE_NAME)
    wait_for_new_blocks(cli, 1)

    def _starting(d):
        m = next(
            (
                x
                for x in distribution["delegator_starting_infos"]
                if x["delegator_address"] == d and x["validator_address"] == target_val
            ),
            None,
        )
        assert m is not None, f"starting info missing for {d}"
        return Decimal(m["starting_info"]["stake"])

    starting1 = _starting(signer1)
    starting2 = _starting(signer2)

    # signer1 (mixed, mainnet val1/val2): recorded factor preserved → starting > cur.
    # Over-clamp bug: starting == cur.
    assert starting1 > cur1, f"signer1 starting={starting1} cur={cur1}"
    # signer2 (silent-only, mainnet val3): exact assignment → starting ≈ cur
    # (LegacyDec truncates to 18 decimals; Python Decimal division has more).
    EPS = Decimal("1e-17")
    assert abs(starting2 - cur2) < EPS, f"signer2 starting={starting2} cur={cur2}"

    cleanup_upgrades_folder(cli.data_dir)

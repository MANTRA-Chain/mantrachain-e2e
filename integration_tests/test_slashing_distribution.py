from pathlib import Path

import pytest
from pystarport.utils import BondStatus, wait_for_block

from .network import setup_custom_mantra
from .slashing_utils import jail_target_and_assert_slashed, setup_dust_delegation

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def slashing_mantra(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp("slashing")
    yield from setup_custom_mantra(
        path,
        26900,
        Path(__file__).parent / "configs/slashing.jsonnet",
        chain=chain,
    )


def test_distribution_slash_event_recorded(slashing_mantra):
    cli = slashing_mantra.cosmos_cli()
    wait_for_block(cli, 5, timeout=60)

    target_val, signer1 = setup_dust_delegation(slashing_mantra, cli)
    val = cli.validator(target_val)
    assert val["status"] == BondStatus.BONDED.value
    assert not val.get("jailed")

    jail_target_and_assert_slashed(slashing_mantra, cli, target_val)

    # regression check: pre-fix this panics with `stake > currentStake`.
    cli.distribution_rewards(signer1)

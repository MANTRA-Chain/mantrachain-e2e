from pathlib import Path

import pytest
from pystarport.utils import BondStatus, wait_for_new_blocks

from .network import setup_custom_mantra
from .utils import DEFAULT_DENOM

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def custom_mantra(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp("mint")
    yield from setup_custom_mantra(
        path,
        27110,
        Path(__file__).parent / "configs/mint.jsonnet",
        chain=chain,
    )


def test_max_supply(custom_mantra):
    cli = custom_mantra.cosmos_cli(i=2)
    val = cli.address("validator", bech="val")
    addr = cli.address("validator")
    gas = 320_000
    amt = 9_000_000_000_000_000_000

    # unbond almost all, check still bonded
    assert (
        cli.unbond_amount(val, f"{amt}{DEFAULT_DENOM}", _from=addr, gas=gas)["code"]
        == 0
    )
    assert cli.validator(val).get("status") == BondStatus.BONDED.value

    # unbond a small amount, should now unbond
    assert cli.unbond_amount(val, f"1{DEFAULT_DENOM}", _from=addr, gas=gas)["code"] == 0
    wait_for_new_blocks(cli, 2)
    assert cli.validator(val).get("status") == BondStatus.UNBONDING.value

    # max supply definition and get current supply
    max_supply = int(700.5 * 10**18)
    supply_before = int(cli.total_supply_of().get("amount"))

    if supply_before >= max_supply:
        pytest.skip("Already at or above max_supply")

    # try to reach max supply
    reached_max = False
    max_blks = 10
    for _ in range(max_blks):
        wait_for_new_blocks(cli, 1)
        current = int(cli.total_supply_of().get("amount"))
        if current >= max_supply * 0.999:
            reached_max = True
            break
    assert reached_max, f"not reach max_supply after {max_blks} blocks."

    # check no excessive minting after limit reached
    supply_at_limit = int(cli.total_supply_of().get("amount"))
    wait_for_new_blocks(cli, 10)
    supply_after = int(cli.total_supply_of().get("amount"))
    assert (
        supply_after <= max_supply
    ), f"supply exceeded max: {supply_after} > {max_supply}"

    diff = supply_after - supply_at_limit
    allowed = max_supply
    assert diff <= allowed, f"supply increased by {diff} after max. allowed: {allowed}"

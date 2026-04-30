import time
from pathlib import Path

import pytest
from pystarport.utils import BondStatus, wait_for_block, wait_for_new_blocks

from .network import setup_custom_mantra
from .utils import DEFAULT_DENOM

pytestmark = pytest.mark.slow

JAILED_NODE_INDEX = 2
JAILED_NODE = f"mantra-canary-net-1-node{JAILED_NODE_INDEX}"


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
    target_cli = slashing_mantra.cosmos_cli(JAILED_NODE_INDEX)
    target_val = target_cli.address("validator", "val")

    wait_for_block(cli, 5, timeout=60)

    val = cli.validator(target_val)
    assert val["status"] == BondStatus.BONDED.value
    assert not val.get("jailed")

    name = "signer1"
    signer1 = cli.address(name)
    # delegate < PowerReduction so consensus power is unchanged
    # (otherwise stopping target would drop alive VP below 2/3).
    rsp = cli.delegate_amount(target_val, f"1{DEFAULT_DENOM}", _from=name, gas=400_000)
    assert rsp["code"] == 0, rsp["raw_log"]
    wait_for_new_blocks(cli, 2, timeout=60)
    cli.distribution_rewards(signer1)

    tokens_bf = int(cli.validator(target_val)["tokens"])

    slashing_mantra.supervisorctl("stop", JAILED_NODE)

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

    v = cli.validator(target_val)
    tokens_af = int(v["tokens"])
    assert (
        tokens_af < tokens_bf
    ), f"validator tokens should be reduced by the slash: {tokens_bf} -> {tokens_af}"

    # regression check: pre-fix this panics with `stake > currentStake`.
    cli.distribution_rewards(signer1)

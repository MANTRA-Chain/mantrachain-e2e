"""Shared helpers for tests that drive the silent-slash code path."""

import time

import pytest
from pystarport.utils import wait_for_new_blocks

JAILED_NODE_INDEX = 2
JAILED_NODE_NAME = f"mantra-canary-net-1-node{JAILED_NODE_INDEX}"


def setup_dust_delegation(mantra, cli, signer_name="signer1"):
    """Delegate 1 amantra (< PowerReduction so consensus power is unchanged
    when JAILED_NODE is stopped) from `signer_name` to the JAILED_NODE
    validator. Returns (target_val, signer_addr)."""
    target_val = mantra.cosmos_cli(JAILED_NODE_INDEX).address("validator", "val")
    signer = cli.address(signer_name)
    rsp = cli.delegate_amount(target_val, "1amantra", _from=signer_name, gas=400_000)
    assert rsp["code"] == 0, rsp["raw_log"]
    wait_for_new_blocks(cli, 2, timeout=60)
    cli.distribution_rewards(signer)
    return target_val, signer


def jail_target_and_assert_slashed(mantra, cli, target_val, deadline=240):
    """Stop JAILED_NODE, wait for the slashing module to jail it, and
    assert the validator's tokens were reduced."""
    tokens_bf = int(cli.validator(target_val)["tokens"])
    mantra.supervisorctl("stop", JAILED_NODE_NAME)

    # window=30, min=0.5 -> jail after 16 missed
    end = time.time() + deadline
    while time.time() < end:
        try:
            wait_for_new_blocks(cli, 2, timeout=60)
        except TimeoutError:
            pytest.fail(
                f"chain stopped producing blocks at height {cli.block_height()} "
                "after stopping validator"
            )
        if cli.validator(target_val).get("jailed"):
            break
    else:
        pytest.fail("validator was not jailed within the wait window")

    tokens_af = int(cli.validator(target_val)["tokens"])
    assert (
        tokens_af < tokens_bf
    ), f"validator tokens should be reduced by the slash: {tokens_bf} -> {tokens_af}"

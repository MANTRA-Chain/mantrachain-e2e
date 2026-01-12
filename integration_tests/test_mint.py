from pathlib import Path

import pytest
from pystarport.utils import wait_for_new_blocks

from integration_tests.utils import module_address, submit_gov_proposal

from .network import setup_custom_mantra


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


def test_max_supply(custom_mantra, tmp_path):
    cli = custom_mantra.cosmos_cli(i=2)
    # params = cli.get_params("mint")
    # max_supply = int(params["max_supply"])
    supply_bf = int(cli.total_supply_of().get("amount"))
    p = cli.get_params("mint")
    max_supply = int(supply_bf * 1.05)
    p["max_supply"] = str(max_supply)
    submit_gov_proposal(
        custom_mantra,
        tmp_path,
        messages=[
            {
                "@type": "/cosmos.mint.v1beta1.MsgUpdateParams",
                "authority": module_address("gov"),
                "params": p,
            },
        ],
        gas=300_000,
    )
    p = cli.get_params("mint")
    assert int(p["max_supply"]) == max_supply, p
    gap_bf = max_supply - supply_bf
    print(f"max_supply: {max_supply}, supply: {supply_bf}, gap: {gap_bf}")
    supplies = [supply_bf]

    for _ in range(10):
        wait_for_new_blocks(cli, 1)
        supplies.append(int(cli.total_supply_of().get("amount")))
        minted = supplies[-1] - supplies[-2]
        gap = max_supply - supplies[-1]
        height = cli.block_height()
        print(f"block {height}, supply: {supplies[-1]}, gap: {gap}, minted: {minted}")
        assert supplies[-1] <= max_supply
        if gap == 0:
            break

    supply_af = supplies[-1]
    gap_af = max_supply - supply_af
    total_minted = supply_af - supply_bf
    print(f"total minted: {total_minted}, gap: {gap_af}")

    assert total_minted > 0
    assert supply_af <= max_supply
    assert gap_af < gap_bf

    # if near max supply, ensure minting almost halts
    if gap_af < max_supply * 0.01 and gap_af < 1000:
        pre = supply_af
        wait_for_new_blocks(cli, 5)
        post = int(cli.total_supply_of().get("amount"))
        assert post - pre < 1000

import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import tomlkit

from .ibc_utils import (
    assert_hermes_transfer,
    assert_ibc_transfer,
    ibc_denom_hash,
    prepare_network,
)
from .network import Mantra
from .upgrade_utils import LEGACY_DENOM, cleanup_upgrades_folder, do_upgrade, post_init
from .utils import (
    ADDRS,
    CMD,
    DEFAULT_DENOM,
    DEFAULT_GAS_AMT,
    eth_to_bech32,
)

pytestmark = [pytest.mark.slow, pytest.mark.skipped]


@pytest.fixture(scope="module")
def custom_mantra(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    nix_name = "upgrade-test-package-recent"
    configdir = Path(__file__).parent
    name = "cosmovisor_with_ibc"
    path = tmp_path_factory.mktemp(name)
    cmd = [
        "nix-build",
        configdir / f"configs/{nix_name}.nix",
    ]
    print(*cmd)
    subprocess.run(cmd, check=True)

    # copy the content so the new directory is writable.
    upgrades = path / "upgrades"
    shutil.copytree("./result", upgrades)
    mod = stat.S_IRWXU
    upgrades.chmod(mod)
    for d in upgrades.iterdir():
        d.chmod(mod)

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


def exec(c, tmp_path):
    cli = c.ibc1.cosmos_cli()
    cli2 = c.ibc2.cosmos_cli()
    signer1 = ADDRS["signer1"]
    community = ADDRS["community"]
    addr_signer1 = eth_to_bech32(signer1)
    prefix = "cosmos"
    port = "transfer"
    channel = "channel-0"
    denom = "atest"

    # evm-canary-net-1 signer2 -> mantra-canary-net-1 signer1 100atest
    transfer_amt = 100
    assert_hermes_transfer(
        c.hermes,
        cli2,
        "signer2",
        transfer_amt,
        cli,
        addr_signer1,
        denom=denom,
        prefix=prefix,
    )

    # mantra-canary-net-1 signer1 -> evm-canary-net-1 community eth addr with 5 baseunit
    path = f"{port}/{channel}/{LEGACY_DENOM}"
    denom_hash = ibc_denom_hash(path)
    dst_denom = f"ibc/{denom_hash}"
    amount = 5
    gas_prices = f"1{LEGACY_DENOM}"

    assert_ibc_transfer(
        cli,
        cli2,
        addr_signer1,
        community,
        amount,
        dst_denom,
        src_denom=LEGACY_DENOM,
        gas_prices=gas_prices,
    )

    target_height = cli.block_height() + 15
    cli = do_upgrade(c.ibc1, "v7.0.0-rc0", target_height, denom=LEGACY_DENOM)

    c.ibc1.supervisorctl("stop", "relayer-demo")
    rly_cfg = c.hermes.configpath
    cfg = tomlkit.parse(rly_cfg.read_text())
    cfg["chains"][1]["gas_price"] = {"denom": DEFAULT_DENOM, "price": DEFAULT_GAS_AMT}
    rly_cfg.write_text(tomlkit.dumps(cfg))
    c.ibc1.supervisorctl("start", "relayer-demo")

    # mantra-canary-net-1 signer1 -> evm-canary-net-1 community eth addr with 5 baseunit
    path = f"{port}/{channel}/{DEFAULT_DENOM}"
    denom_hash = ibc_denom_hash(path)
    dst_denom = f"ibc/{denom_hash}"
    assert_ibc_transfer(
        cli,
        cli2,
        addr_signer1,
        community,
        amount,
        dst_denom,
    )

    # evm-canary-net-1 signer2 -> mantra-canary-net-1 signer1 100atest
    assert_hermes_transfer(
        c.hermes,
        cli2,
        "signer2",
        transfer_amt,
        cli,
        addr_signer1,
        denom=denom,
        prefix=prefix,
    )


def test_cosmovisor_upgrade(custom_mantra: Mantra, tmp_path):
    exec(custom_mantra, tmp_path)
    cleanup_upgrades_folder(custom_mantra.ibc1.cosmos_cli().data_dir)

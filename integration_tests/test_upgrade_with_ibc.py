import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import tomlkit

from .ibc_utils import hermes_transfer, ibc_denom_hash, prepare_network
from .network import Mantra
from .upgrade_utils import LEGACY_DENOM, cleanup_upgrades_folder, do_upgrade, post_init
from .utils import (
    ADDRS,
    CMD,
    DEFAULT_DENOM,
    DEFAULT_GAS_AMT,
    escrow_address,
    eth_to_bech32,
    wait_for_balance_change,
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
    prefix = "cosmos"
    addr_signer1 = eth_to_bech32(signer1)
    addr_signer2 = eth_to_bech32(ADDRS["signer2"], prefix=prefix)
    addr_community = eth_to_bech32(community, prefix=prefix)
    denom = "atest"

    # evm-canary-net-1 signer2 -> mantra-canary-net-1 signer1 100atest
    transfer_amt = 100
    src_chain = "evm-canary-net-1"
    dst_chain = "mantra-canary-net-1"

    port = "transfer"
    channel = "channel-0"
    path = f"{port}/{channel}/{denom}"

    escrow_addr = hermes_transfer(
        c,
        src_chain,
        "signer2",
        transfer_amt,
        dst_chain,
        addr_signer1,
        denom=denom,
        prefix=prefix,
    )
    denom_hash = ibc_denom_hash(path)
    dst_denom = f"ibc/{denom_hash}"
    signer1_balance_bf = cli.balance(addr_signer1, dst_denom)
    signer1_balance = wait_for_balance_change(
        cli, addr_signer1, dst_denom, signer1_balance_bf
    )
    assert signer1_balance == signer1_balance_bf + transfer_amt
    assert cli.ibc_denom_hash(path) == denom_hash
    escrow_balance = cli2.balance(escrow_addr, denom=denom)
    assert escrow_balance == transfer_amt

    # mantra-canary-net-1 signer1 -> evm-canary-net-1 signer2 eth addr with 5 baseunit
    path = f"{port}/{channel}/{LEGACY_DENOM}"
    denom_hash = ibc_denom_hash(path)
    dst_legacy_denom = f"ibc/{denom_hash}"
    amount = 5
    gas_prices = f"1{LEGACY_DENOM}"
    rsp = cli.ibc_transfer(
        addr_signer2,
        f"{amount}{LEGACY_DENOM}",
        channel,
        from_=addr_signer1,
        gas_prices=gas_prices,
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    signer2_balance_bf = cli2.balance(addr_signer2, dst_legacy_denom)
    signer2_balance = wait_for_balance_change(
        cli2, addr_signer2, dst_legacy_denom, signer2_balance_bf
    )
    assert signer2_balance == signer2_balance_bf + amount

    target_height = cli.block_height() + 15
    cli = do_upgrade(c.ibc1, "v7.0.0-rc0", target_height, denom=LEGACY_DENOM)

    c.ibc1.supervisorctl("stop", "relayer-demo")
    rly_cfg = c.hermes.configpath
    cfg = tomlkit.parse(rly_cfg.read_text())
    cfg["chains"][1]["gas_price"] = {"denom": DEFAULT_DENOM, "price": DEFAULT_GAS_AMT}
    rly_cfg.write_text(tomlkit.dumps(cfg))
    c.ibc1.supervisorctl("start", "relayer-demo")

    # evm-canary signer2 -> mantra-canary signer1 eth addr with 5 legacy baseunit
    transfer_amt = 5
    src_chain = "evm-canary-net-1"
    dst_chain = "mantra-canary-net-1"

    port = "transfer"
    channel = "channel-0"

    escrow_addr = hermes_transfer(
        c,
        src_chain,
        "signer2",
        transfer_amt,
        dst_chain,
        addr_signer1,
        denom=dst_legacy_denom,
        prefix=prefix,
    )
    signer1_balance_bf = cli.balance(addr_signer1, DEFAULT_DENOM)
    escrow_addr = escrow_address(port, channel)
    escrow_balance_bf = cli.balance(escrow_addr, denom=LEGACY_DENOM)
    signer1_balance = wait_for_balance_change(
        cli, addr_signer1, DEFAULT_DENOM, signer1_balance_bf
    )
    # 5 legacy baseunit = 5 * 4e12 new baseunit
    assert signer1_balance == signer1_balance_bf + transfer_amt * 4 * 10**12
    # verify escrow balance decreased by transfer_amt
    escrow_balance = wait_for_balance_change(
        cli, escrow_addr, LEGACY_DENOM, escrow_balance_bf
    )
    assert escrow_balance_bf == escrow_balance + transfer_amt

    # mantra-canary-net-1 signer1 -> evm-canary-net-1 community eth addr with 5 baseunit
    rsp = cli.ibc_transfer(
        community,
        f"{amount}{DEFAULT_DENOM}",
        channel,
        from_=addr_signer1,
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    path = f"{port}/{channel}/{DEFAULT_DENOM}"
    denom_hash = ibc_denom_hash(path)
    dst_denom = f"ibc/{denom_hash}"

    community_balance_bf = cli2.balance(addr_community, dst_denom)
    community_balance = wait_for_balance_change(
        cli2, addr_community, dst_denom, community_balance_bf
    )
    assert community_balance == community_balance_bf + amount

    # evm-canary-net-1 signer2 -> mantra-canary-net-1 signer1 100atest
    src_chain = "evm-canary-net-1"
    dst_chain = "mantra-canary-net-1"

    escrow_addr = hermes_transfer(
        c,
        src_chain,
        "signer2",
        transfer_amt,
        dst_chain,
        addr_signer1,
        denom=denom,
        prefix=prefix,
    )

    path = f"{port}/{channel}/{denom}"
    denom_hash = ibc_denom_hash(path)
    dst_denom = f"ibc/{denom_hash}"
    signer1_balance_bf = cli.balance(addr_signer1, dst_denom)
    signer1_balance = wait_for_balance_change(
        cli, addr_signer1, dst_denom, signer1_balance_bf
    )
    assert signer1_balance == signer1_balance_bf + transfer_amt
    assert cli.ibc_denom_hash(path) == denom_hash
    assert cli2.balance(escrow_addr, denom=denom) == escrow_balance + transfer_amt


def test_cosmovisor_upgrade(custom_mantra: Mantra, tmp_path):
    exec(custom_mantra, tmp_path)
    cleanup_upgrades_folder(custom_mantra.ibc1.cosmos_cli().data_dir)

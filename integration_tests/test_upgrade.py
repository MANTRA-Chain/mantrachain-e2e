import time

import pytest
import requests
import tomlkit
from pystarport import ports

from .network import Mantra
from .upgrade_utils import (
    check_basic_eth_tx,
    cleanup_upgrades_folder,
    do_upgrade,
    setup_mantra_upgrade,
)
from .utils import (
    CONTRACTS,
    DEFAULT_FEE,
    DEFAULT_GAS_PRICE,
    assert_create_tokenfactory_denom,
    assert_set_tokenfactory_denom,
    assert_transfer,
    deploy_contract,
    derive_new_account,
    eth_to_bech32,
    get_balance,
    module_address,
    submit_gov_proposal,
    wait_for_new_blocks,
    wait_for_port,
)

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def custom_mantra(tmp_path_factory):
    yield from setup_mantra_upgrade(
        tmp_path_factory, "upgrade-test-package", "cosmovisor", "genesis"
    )


def patch_app_mempool(path, max_txs):
    cfg = tomlkit.parse(path.read_text())
    cfg["mempool"] = {
        "max-txs": max_txs,
    }
    path.write_text(tomlkit.dumps(cfg))


def get_tx(base_port, hash):
    p = ports.api_port(base_port)
    url = f"http://127.0.0.1:{p}/cosmos/tx/v1beta1/txs/{hash}"
    return requests.get(url).json()


def is_subset(small, big):
    if isinstance(small, dict) and isinstance(big, dict):
        for k, v in small.items():
            if k not in big or not is_subset(v, big[k]):
                return False
        return True
    elif isinstance(small, list) and isinstance(big, list):
        return all(any(is_subset(sv, bv) for bv in big) for sv in small)
    else:
        return small == big


def exec(c, tmp_path):
    cli = c.cosmos_cli()
    base_port = c.base_port(0)
    community = "community"

    c.supervisorctl(
        "start",
        "mantra-canary-net-1-node0",
        "mantra-canary-net-1-node1",
        "mantra-canary-net-1-node2",
    )
    wait_for_new_blocks(cli, 1)

    addr_a = cli.address(community)

    subdenom = f"admin{time.time()}"
    gas_prices = "1uom"

    p = cli.get_params("feemarket")
    p["min_base_gas_price"] = "0.010000000000000000"
    gov_txhash = submit_gov_proposal(
        c,
        tmp_path,
        messages=[
            {
                "@type": "/feemarket.feemarket.v1.MsgParams",
                "authority": module_address("gov"),
                "params": p,
            }
        ],
        gas=250000,
        gas_prices=gas_prices,
    )["txhash"]
    gov_tx_bf = get_tx(base_port, gov_txhash)
    assert gov_tx_bf
    assert cli.get_params("feemarket") == p
    res = cli.query_proposals()
    assert len(res) > 0, res

    height = cli.block_height()
    target_height = height + 15

    denom = assert_create_tokenfactory_denom(
        cli, subdenom, is_legacy=True, _from=addr_a, gas_prices=gas_prices
    )
    assert_set_tokenfactory_denom(
        cli, tmp_path, denom, _from=addr_a, gas_prices=gas_prices
    )

    cli = do_upgrade(c, "v5", target_height)
    acc_b = derive_new_account(100)
    addr_b = eth_to_bech32(acc_b.address)

    wait_for_port(ports.evmrpc_port(c.base_port(0)))
    balance = get_balance(cli, community)
    amt = int(balance - DEFAULT_FEE - 1e6)
    assert_transfer(cli, addr_a, addr_b, amt=amt)
    # check set contract tx works
    contract = deploy_contract(c.w3, CONTRACTS["Greeter"], key=acc_b.key)
    assert "Hello" == contract.caller.greet()
    check_basic_eth_tx(c.w3, contract, acc_b, addr_a, "world")
    wait_for_new_blocks(cli, 3)

    height = cli.block_height()
    target_height = height + 15
    cli = do_upgrade(c, "v5.0.0-rc1", target_height)

    with pytest.raises(AssertionError, match="no concrete type registered"):
        cli.query_proposals()

    print(c.supervisorctl("stop", "mantra-canary-net-1-node1"))
    # TODO: remove after https://github.com/cosmos/evm/pull/313 backport to v5.0.0-rc1
    time.sleep(5)
    patch_app_mempool(c.cosmos_cli(i=1).data_dir / "config/app.toml", 5000)
    print(c.supervisorctl("start", "mantra-canary-net-1-node1"))

    wait_for_port(ports.evmrpc_port(c.base_port(0)))
    check_basic_eth_tx(c.w3, contract, acc_b, addr_a, "world!")
    wait_for_new_blocks(cli, 3)

    height = cli.block_height()
    target_height = height + 15
    cli = do_upgrade(c, "v5.0.0-rc2", target_height)

    wait_for_port(ports.evmrpc_port(c.base_port(0)))
    check_basic_eth_tx(c.w3, contract, acc_b, addr_a, "world!")
    wait_for_new_blocks(cli, 3)
    # check already registered ethContractAddr doesn't break upgrade
    subdenom = f"admin{time.time()}"
    denom = assert_create_tokenfactory_denom(
        cli, subdenom, is_legacy=True, _from=addr_a, gas=620000
    )

    height = cli.block_height()
    target_height = height + 15
    cli = do_upgrade(c, "v5.0.0-rc3", target_height)
    check_basic_eth_tx(c.w3, contract, acc_b, addr_a, "world!!")

    metadata = cli.query_bank_denom_metadata(denom)
    assert metadata == {
        "denom_units": [{"denom": denom}],
        "base": denom,
        "display": denom,
        "name": denom,
        "symbol": denom,
    }, metadata
    allow = cli.get_params("evm").get("params", {}).get("allow_unprotected_txs")
    assert allow is True, "allow_unprotected_txs should be true"

    height = cli.block_height()
    target_height = height + 15
    cli = do_upgrade(c, "v5.0.0-rc4", target_height)
    check_basic_eth_tx(c.w3, contract, acc_b, addr_a, "world!!!")

    height = cli.block_height()
    target_height = height + 15
    cli = do_upgrade(c, "v5.0.0-rc5", target_height, gas_prices=DEFAULT_GAS_PRICE)

    res = cli.query_proposals()
    assert len(res) > 0, res
    gov_tx_af = get_tx(base_port, gov_txhash)
    assert is_subset(gov_tx_bf, gov_tx_af)

    height = cli.block_height()
    target_height = height + 15

    cli = do_upgrade(c, "v5.0.0-rc6", target_height, gas_prices=DEFAULT_GAS_PRICE)
    check_basic_eth_tx(c.w3, contract, acc_b, addr_a, "world rc6")


def test_cosmovisor_upgrade(custom_mantra: Mantra, tmp_path):
    exec(custom_mantra, tmp_path)
    cleanup_upgrades_folder(custom_mantra.cosmos_cli().data_dir)

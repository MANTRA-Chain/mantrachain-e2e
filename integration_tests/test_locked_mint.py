import pytest
from eth_contract.contract import Contract
from eth_contract.create2 import create2_address
from eth_contract.deploy_utils import (
    ensure_create2_deployed,
    ensure_deployed_by_create2,
)
from eth_contract.utils import get_initcode

from .test_staking_precompile import get_validators, send_value
from .utils import ACCOUNTS, build_contract, eth_to_bech32, wait_for_eth_tx_result

pytestmark = pytest.mark.asyncio

LOCKED = 10**18  # permanently-locked coins the weapon delegates
MINT = 3 * 10**17  # finite phantom mint, well under the sdk.Int ceiling
DEPLOYER_SALT = 0xDEB10
WEAPON_SALT = 0x10CCED


def total_supply(cli):
    return int(cli.total_supply_of()["amount"])


async def test_locked_coin_finite_mint(mantra):
    await _finite_mint(mantra.cosmos_cli(), mantra.async_w3)


@pytest.mark.connect
async def test_connect_locked_coin_finite_mint(connect_mantra, tmp_path):
    await _finite_mint(connect_mantra.cosmos_cli(tmp_path), connect_mantra.async_w3)


async def _finite_mint(cli, w3):
    acct = ACCOUNTS["community"]
    beneficiary = ACCOUNTS["signer1"].address
    cli.address("community")  # recover the signer key into the temp keyring

    validator = cli.debug_addr((await get_validators(w3))[0][0], bech="val")
    await ensure_create2_deployed(w3, acct)

    deployer_art = build_contract("LockedMintDeployer")
    deployer = await ensure_deployed_by_create2(
        w3, acct, get_initcode(deployer_art), salt=DEPLOYER_SALT
    )

    # the weapon lands at CREATE2(deployer, WEAPON_SALT, weaponInit)
    weapon_init = get_initcode(build_contract("LockedMintWeapon"))
    weapon = create2_address(weapon_init, WEAPON_SALT, factory=deployer)

    # make that address a permanent-locked account before it holds code, so the
    # weapon's `this` owns delegatable locked coins with 0 spendable balance
    rsp = cli._tx(
        "vesting",
        "create-permanent-locked-account",
        eth_to_bech32(weapon),
        f"{LOCKED}amantra",
        **{"from": "community"},
    )
    assert rsp.get("code") == 0, rsp

    supply_before = total_supply(cli)
    ben_before = await w3.eth.get_balance(beneficiary)

    # one tx: CREATE2 the weapon, delegate all locked coins (underflow), mint a
    # finite amount out, then selfdestruct to discard the ~2**256 wrap
    calldata = (
        Contract(deployer_art["abi"])
        .fns.run(
            WEAPON_SALT.to_bytes(32, "big"),
            weapon_init,
            validator,
            LOCKED,
            beneficiary,
            MINT,
        )
        .data
    )
    height = cli.block_height()
    txh = await send_value(w3, acct, deployer, 0, calldata, gas=5_000_000)
    res = await wait_for_eth_tx_result(cli, w3, txh, height)

    ben_gain = (await w3.eth.get_balance(beneficiary)) - ben_before
    minted = total_supply(cli) - supply_before
    print(f"code={res.get('code')} ben_gain={ben_gain} supply_delta={minted}")

    assert ben_gain <= 0, (
        f"exploit reproduced: beneficiary conjured {ben_gain} amantra from a "
        f"locked-coin delegate (supply_delta={minted})"
    )

import json
from pathlib import Path

import pytest
from eth_contract.contract import Contract
from eth_contract.create2 import create2_address, create2_deploy
from eth_contract.create3 import CREATEX_FACTORY, create3_address, create3_deploy
from eth_contract.deploy_utils import (
    ensure_create2_deployed,
    ensure_createx_deployed,
    ensure_deployed_by_create2,
    ensure_multicall3_deployed,
)
from eth_contract.erc20 import ERC20
from eth_contract.multicall3 import (
    MULTICALL3,
    MULTICALL3_ADDRESS,
    Call3Value,
    multicall,
)
from eth_contract.utils import (
    ZERO_ADDRESS,
    balance_of,
    get_initcode,
)
from eth_contract.weth import WETH
from web3 import AsyncWeb3
from web3.types import Wei

from .network import setup_custom_mantra
from .utils import ADDRS

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def mantra_replay(tmp_path_factory):
    path = tmp_path_factory.mktemp("mantra-replay")
    yield from setup_custom_mantra(
        path, 26600, Path(__file__).parent / "configs/allow_replay.jsonnet"
    )


MockERC20_ARTIFACT = json.loads(
    Path(__file__).parent.joinpath("contracts/contracts/MockERC20.json").read_text()
)
WETH_SALT = 999
WETH9_ARTIFACT = json.loads(
    Path(__file__).parent.joinpath("contracts/contracts/WETH9.json").read_text()
)
WETH_ADDRESS = create2_address(get_initcode(WETH9_ARTIFACT), WETH_SALT)
MULTICALL3ROUTER_ARTIFACT = json.loads(
    Path(__file__)
    .parent.joinpath("contracts/contracts/Multicall3Router.json")
    .read_text()
)
MULTICALL3ROUTER = create2_address(
    get_initcode(MULTICALL3ROUTER_ARTIFACT, MULTICALL3_ADDRESS)
)


async def deploy_weth(w3: AsyncWeb3) -> None:
    sender = (await w3.eth.accounts)[0]
    address = await create2_deploy(
        w3, sender, get_initcode(WETH9_ARTIFACT), salt=WETH_SALT
    )
    assert address == WETH_ADDRESS, f"Expected {WETH_ADDRESS}, got {address}"


@pytest.mark.skip(reason="fixed in evm is reverted")
async def test_flow(mantra_replay):
    w3 = mantra_replay.async_w3
    await ensure_create2_deployed(w3)
    await ensure_multicall3_deployed(w3)
    await ensure_createx_deployed(w3)
    await deploy_weth(w3)
    assert MULTICALL3ROUTER == await ensure_deployed_by_create2(
        w3, get_initcode(MULTICALL3ROUTER_ARTIFACT, MULTICALL3_ADDRESS)
    )
    initcode = get_initcode(MockERC20_ARTIFACT, "TEST", "TEST", 18)
    owner = (await w3.eth.accounts)[0]

    # test_create2_deploy
    salt = 100
    token = await create2_deploy(w3, owner, initcode, salt=salt)
    assert (
        token
        == create2_address(initcode, salt)
        == "0x854d811d90C6E81B84b29C1d7ed957843cF87bba"
    )
    assert await ERC20.fns.balanceOf(owner).call(w3, to=token) == 0
    await ERC20.fns.mint(owner, 1000).transact(w3, owner, to=token)
    assert await ERC20.fns.balanceOf(owner).call(w3, to=token) == 1000

    # test_create3_deploy
    salt = 200
    token = await create3_deploy(
        w3, owner, initcode, salt=salt, factory=CREATEX_FACTORY, value=Wei(0)
    )
    assert (
        token == create3_address(salt) == "0x60f7B32B5799838a480572Aee2A8F0355f607b38"
    )
    assert await ERC20.fns.balanceOf(owner).call(w3, to=token) == 0
    await ERC20.fns.mint(owner, 1000).transact(w3, owner, to=token)
    assert await ERC20.fns.balanceOf(owner).call(w3, to=token) == 1000

    # test_weth
    weth = WETH(to=WETH_ADDRESS)
    before = await balance_of(w3, ZERO_ADDRESS, owner)
    receipt = await weth.fns.deposit().transact(w3, owner, value=1000)
    fee = receipt["effectiveGasPrice"] * receipt["gasUsed"]
    await balance_of(w3, WETH_ADDRESS, owner) == 1000
    receipt = await weth.fns.withdraw(1000).transact(w3, owner)
    fee += receipt["effectiveGasPrice"] * receipt["gasUsed"]
    await balance_of(w3, WETH_ADDRESS, owner) == 0
    assert await balance_of(w3, ZERO_ADDRESS, owner) == before - fee

    # test_batch_call
    users = [ADDRS[key] for key in ["community", "signer1", "signer2"]]
    amount = 1000
    amount_all = amount * len(users)

    balances = [(WETH_ADDRESS, ERC20.fns.balanceOf(user)) for user in users]
    assert all(x == 0 for x in await multicall(w3, balances))
    await MULTICALL3.fns.aggregate3Value(
        [Call3Value(WETH_ADDRESS, False, amount_all, weth.fns.deposit().data)]
        + [
            Call3Value(WETH_ADDRESS, False, 0, ERC20.fns.transfer(user, amount).data)
            for user in users
        ]
    ).transact(w3, users[0], value=amount_all)
    assert all(x == amount for x in await multicall(w3, balances))

    for user in users:
        await ERC20.fns.approve(MULTICALL3_ADDRESS, amount).transact(
            w3, user, to=WETH_ADDRESS
        )

    await MULTICALL3.fns.aggregate3Value(
        [
            Call3Value(
                WETH_ADDRESS,
                data=ERC20.fns.transferFrom(user, MULTICALL3_ADDRESS, amount).data,
            )
            for user in users
        ]
        + [
            Call3Value(
                WETH_ADDRESS,
                data=weth.fns.transferFrom(
                    MULTICALL3_ADDRESS, users[0], amount_all
                ).data,
            ),
        ]
    ).transact(w3, users[0])
    await weth.fns.withdraw(amount_all).transact(w3, users[0], to=WETH_ADDRESS)
    assert all(x == 0 for x in await multicall(w3, balances))
    assert await balance_of(w3, WETH_ADDRESS, MULTICALL3_ADDRESS) == 0

    # test_multicall3_router
    amount_all = amount * len(users)
    router = Contract(MULTICALL3ROUTER_ARTIFACT["abi"])
    multicall3 = MULTICALL3ROUTER

    balances = [(WETH_ADDRESS, ERC20.fns.balanceOf(user)) for user in users]
    assert all(x == 0 for x in await multicall(w3, balances))

    before = await balance_of(w3, ZERO_ADDRESS, users[0])

    # convert amount_all into WETH and distribute to users
    receipt = await MULTICALL3.fns.aggregate3Value(
        [Call3Value(WETH_ADDRESS, False, amount_all, WETH.fns.deposit().data)]
        + [
            Call3Value(WETH_ADDRESS, False, 0, ERC20.fns.transfer(user, amount).data)
            for user in users
        ]
    ).transact(w3, users[0], to=multicall3, value=amount_all)
    before -= receipt["effectiveGasPrice"] * receipt["gasUsed"]
    # check users's weth balances
    assert all(x == amount for x in await multicall(w3, balances))

    # approve multicall3 to transfer WETH on behalf of users
    for i, user in enumerate(users):
        receipt = await ERC20.fns.approve(multicall3, amount).transact(
            w3, user, to=WETH_ADDRESS
        )
        if i == 0:
            before -= receipt["effectiveGasPrice"] * receipt["gasUsed"]

    # transfer WETH from all users to multicall3, withdraw it,
    # and send back to users[0]
    receipt = await MULTICALL3.fns.aggregate3Value(
        [
            Call3Value(
                WETH_ADDRESS, data=ERC20.fns.transferFrom(user, multicall3, amount).data
            )
            for user in users
        ]
        + [
            Call3Value(WETH_ADDRESS, data=WETH.fns.withdraw(amount_all).data),
            Call3Value(
                multicall3,
                data=router.fns.sellToPool(ZERO_ADDRESS, 10000, users[0], 0, b"").data,
            ),
        ]
    ).transact(w3, users[0], to=multicall3)
    before -= receipt["effectiveGasPrice"] * receipt["gasUsed"]

    assert all(x == 0 for x in await multicall(w3, balances))
    assert await balance_of(w3, WETH_ADDRESS, multicall3) == 0
    assert await balance_of(w3, ZERO_ADDRESS, multicall3) == 0

    # user get all funds back other than gas fees
    assert await balance_of(w3, ZERO_ADDRESS, users[0]) == before

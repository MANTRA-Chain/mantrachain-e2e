"""
https://eips.ethereum.org/EIPS/eip-2535
"""

import pytest
import web3
from eth_contract.contract import Contract
from eth_contract.deploy_utils import (
    ensure_create2_deployed,
    ensure_deployed_by_create2,
)
from eth_contract.utils import get_initcode, send_transaction
from web3 import AsyncWeb3

from .diamond import Facet, FacetCut, FacetCutAction, cut_diamond
from .utils import ACCOUNTS, build_contract_solcx, selectors

DIAMOND_ARTIFACT = build_contract_solcx("Diamond")
GREETER_ARTIFACT = build_contract_solcx("Greeter")

IDiamondCut = Contract(DIAMOND_ARTIFACT["IDiamondCut"]["abi"])
IDiamondLoupe = Contract(DIAMOND_ARTIFACT["IDiamondLoupe"]["abi"])
IERC173 = Contract(DIAMOND_ARTIFACT["IERC173"]["abi"])
IGreeter1 = Contract(GREETER_ARTIFACT["Greeter"]["abi"])
IGreeter2 = Contract(GREETER_ARTIFACT["GreeterV2"]["abi"])

DIAMOND_CUT_SELECTORS = selectors(DIAMOND_ARTIFACT["IDiamondCut"])
DIAMOND_LOUPE_SELECTORS = selectors(DIAMOND_ARTIFACT["IDiamondLoupe"])
OWNERSHIP_SELECTORS = selectors(DIAMOND_ARTIFACT["IERC173"])
GREETER1_SELECTORS = selectors(GREETER_ARTIFACT["Greeter"])
GREETER2_SELECTORS = selectors(GREETER_ARTIFACT["GreeterV2"])


async def deploy_diamond(w3: AsyncWeb3, deployer):
    await ensure_create2_deployed(w3, deployer)
    cut_address = await ensure_deployed_by_create2(
        w3, deployer, get_initcode(DIAMOND_ARTIFACT["DiamondCutFacet"])
    )
    loupe_address = await ensure_deployed_by_create2(
        w3, deployer, get_initcode(DIAMOND_ARTIFACT["DiamondLoupeFacet"])
    )
    cut_cut = FacetCut(cut_address, FacetCutAction.ADD, DIAMOND_CUT_SELECTORS)
    loupe_cut = FacetCut(loupe_address, FacetCutAction.ADD, DIAMOND_LOUPE_SELECTORS)

    # always deploy a new contract
    receipt = await send_transaction(
        w3,
        deployer,
        data=get_initcode(
            DIAMOND_ARTIFACT["Diamond"], [cut_cut, loupe_cut], deployer.address
        ),
    )
    return receipt["contractAddress"]


async def test_diamond(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    deployer = ACCOUNTS["community"]
    diamond = await deploy_diamond(w3, deployer)

    # cut diamond
    ownership_address = await ensure_deployed_by_create2(
        w3, deployer, get_initcode(DIAMOND_ARTIFACT["OwnershipFacet"])
    )
    await cut_diamond(
        w3, deployer, diamond, Facet(ownership_address, OWNERSHIP_SELECTORS)
    )

    # test the facet functions via diamond
    assert deployer.address.lower() == await IERC173.fns.owner().call(w3, to=diamond)

    assert ownership_address.lower() == await IDiamondLoupe.fns.facetAddress(
        OWNERSHIP_SELECTORS[0]
    ).call(w3, to=diamond)


async def test_cut_diamond(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    deployer = ACCOUNTS["community"]
    diamond = await deploy_diamond(w3, deployer)

    greeter1 = await ensure_deployed_by_create2(
        w3, deployer, get_initcode(GREETER_ARTIFACT["Greeter"])
    )
    greeter2 = await ensure_deployed_by_create2(
        w3, deployer, get_initcode(GREETER_ARTIFACT["GreeterV2"])
    )

    await cut_diamond(w3, deployer, diamond, Facet(greeter1, GREETER1_SELECTORS))

    # set greet message to diamond state
    msg = "Hello from 💎"
    await IGreeter1.fns.setGreeting(msg).transact(w3, deployer, to=diamond)
    assert msg == await IGreeter1.fns.greet().call(w3, to=diamond)

    assert "toRemove" == await IGreeter1.fns.toRemove().call(w3, to=diamond)

    # upgrade to GreeterV2
    await cut_diamond(w3, deployer, diamond, Facet(greeter2, GREETER2_SELECTORS))
    assert "hello from v2" == await IGreeter1.fns.greet().call(w3, to=diamond)

    # method removed
    with pytest.raises(web3.exceptions.ContractCustomError):
        await IGreeter1.fns.toRemove().call(w3, to=diamond)

    # new method
    assert "newMethod" == await IGreeter2.fns.newMethod().call(w3, to=diamond)

"""
https://eips.ethereum.org/EIPS/eip-2535
"""

from enum import IntEnum
from typing import NamedTuple

import pytest
from eth_contract.contract import Contract
from eth_contract.create2 import create2_deploy
from eth_contract.deploy_utils import ensure_create2_deployed
from eth_contract.utils import ZERO_ADDRESS, get_initcode
from web3 import AsyncWeb3

from .utils import ACCOUNTS, build_contract


class FacetCutAction(IntEnum):
    ADD, REPLACE, REMOVE = range(3)


class FacetCut(NamedTuple):
    facet_address: str
    action: FacetCutAction
    function_selectors: list[bytes]


class Facet(NamedTuple):
    facet_address: str
    function_selectors: list[bytes]


IDiamondCut = Contract.from_abi(
    [
        "struct FacetCut { address facetAddress; uint8 action; "
        "bytes4[] functionSelectors; }",
        "function diamondCut(FacetCut[] _diamondCut, address _init, bytes _calldata)",
    ]
)

IDiamondLoupe = Contract.from_abi(
    [
        "struct Facet { address facetAddress; bytes4[] functionSelectors; }",
        "function facets() returns (Facet[] facets_)",
        "function facetFunctionSelectors(address _facet) returns "
        "(bytes4[] memory facetFunctionSelectors_)",
        "function facetAddresses() returns (address[] facetAddresses_)",
        "function facetAddress(bytes4 _functionSelector) returns "
        "(address facetAddress_)",
    ]
)

IERC173 = Contract.from_abi(
    [
        "function owner() returns (address owner_)",
        "function transferOwnership(address _newOwner)",
    ]
)

DIAMOND_CUT_SELECTORS = [IDiamondCut.fns.diamondCut.selector]
DIAMOND_LOUPE_SELECTORS = [
    IDiamondLoupe.fns.facets.selector,
    IDiamondLoupe.fns.facetFunctionSelectors.selector,
    IDiamondLoupe.fns.facetAddresses.selector,
    IDiamondLoupe.fns.facetAddress.selector,
]
OWNERSHIP_SELECTORS = [
    IERC173.fns.owner.selector,
    IERC173.fns.transferOwnership.selector,
]


@pytest.mark.asyncio
async def test_diamond(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    deployer = ACCOUNTS["community"]
    await ensure_create2_deployed(w3, deployer)

    diamond_artifact = build_contract("Diamond", contract="Diamond")
    cut_artifact = build_contract("Diamond", contract="DiamondCutFacet")
    loupe_artifact = build_contract("Diamond", contract="DiamondLoupeFacet")
    ownership_artifact = build_contract("Diamond", contract="OwnershipFacet")

    cut_address = await create2_deploy(w3, deployer, get_initcode(cut_artifact))
    loupe_address = await create2_deploy(w3, deployer, get_initcode(loupe_artifact))
    ownership_address = await create2_deploy(
        w3, deployer, get_initcode(ownership_artifact)
    )

    cut_cut = FacetCut(cut_address, FacetCutAction.ADD, DIAMOND_CUT_SELECTORS)
    loupe_cut = FacetCut(loupe_address, FacetCutAction.ADD, DIAMOND_LOUPE_SELECTORS)
    ownership_cut = FacetCut(ownership_address, FacetCutAction.ADD, OWNERSHIP_SELECTORS)

    # register the very core facet in constructor
    diamond_address = await create2_deploy(
        w3, deployer, get_initcode(diamond_artifact, [cut_cut], deployer.address)
    )

    # register extra facets using diamondCut
    await IDiamondCut.fns.diamondCut(
        [loupe_cut, ownership_cut], ZERO_ADDRESS, b""
    ).transact(w3, deployer, to=diamond_address)

    # test the facet functions via diamond
    assert deployer.address.lower() == await IERC173.fns.owner().call(
        w3, to=diamond_address
    )
    exp_facets = (
        Facet(cut_address.lower(), tuple(DIAMOND_CUT_SELECTORS)),
        Facet(loupe_address.lower(), tuple(DIAMOND_LOUPE_SELECTORS)),
        Facet(ownership_address.lower(), tuple(OWNERSHIP_SELECTORS)),
    )
    assert exp_facets == await IDiamondLoupe.fns.facets().call(w3, to=diamond_address)

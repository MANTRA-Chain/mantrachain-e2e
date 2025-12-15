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

from .utils import ACCOUNTS, build_contract_solcx, selectors


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

IGreeter = Contract.from_abi(
    [
        "function greet() returns (string)",
        "function setGreeting(string _greeting)",
    ]
)

DIAMOND_ARTIFACT = build_contract_solcx("Diamond")
DIAMOND_CUT_SELECTORS = selectors(DIAMOND_ARTIFACT["IDiamondCut"])
DIAMOND_LOUPE_SELECTORS = selectors(DIAMOND_ARTIFACT["IDiamondLoupe"])
OWNERSHIP_SELECTORS = selectors(DIAMOND_ARTIFACT["IERC173"])
GREETER_ARTIFACT = build_contract_solcx("Greeter")
GREETER_SELECTORS = selectors(GREETER_ARTIFACT["Greeter"])

DIAMOND_SALT_BASE = 0
V2_SALT = 2

contract_cache = {}


async def deploy_greeter(w3: AsyncWeb3, deployer):
    cache_key = "greeter_facet"
    if cache_key in contract_cache:
        return contract_cache[cache_key]

    greeter_address = await create2_deploy(
        w3, deployer, get_initcode(GREETER_ARTIFACT["Greeter"])
    )
    contract_cache[cache_key] = greeter_address
    return greeter_address


async def verify_facet_address(
    w3: AsyncWeb3, diamond_address: str, selector: bytes, expected_address: str
):
    facet_addr = await IDiamondLoupe.fns.facetAddress(selector).call(
        w3, to=diamond_address
    )
    assert facet_addr.lower() == expected_address.lower()


async def set_and_verify_greeting(
    w3: AsyncWeb3, deployer, diamond_address, message: str
):
    await IGreeter.fns.setGreeting(message).transact(w3, deployer, to=diamond_address)
    result = await IGreeter.fns.greet().call(w3, to=diamond_address)
    assert result == message
    return result


async def deploy_diamond(w3: AsyncWeb3, deployer, extra_facets=None):
    cache_key = "diamond_facets"
    if cache_key in contract_cache:
        cut_address, loupe_address, ownership_address = contract_cache[cache_key]
    else:
        await ensure_create2_deployed(w3, deployer)
        cut_address = await create2_deploy(
            w3, deployer, get_initcode(DIAMOND_ARTIFACT["DiamondCutFacet"])
        )
        loupe_address = await create2_deploy(
            w3, deployer, get_initcode(DIAMOND_ARTIFACT["DiamondLoupeFacet"])
        )
        ownership_address = await create2_deploy(
            w3, deployer, get_initcode(DIAMOND_ARTIFACT["OwnershipFacet"])
        )
        contract_cache[cache_key] = (cut_address, loupe_address, ownership_address)
    cut_cut = FacetCut(cut_address, FacetCutAction.ADD, DIAMOND_CUT_SELECTORS)
    loupe_cut = FacetCut(loupe_address, FacetCutAction.ADD, DIAMOND_LOUPE_SELECTORS)
    ownership_cut = FacetCut(ownership_address, FacetCutAction.ADD, OWNERSHIP_SELECTORS)

    # register the very core facet in constructor
    facets_in_constructor = [cut_cut]
    if extra_facets:
        facets_in_constructor.extend(extra_facets)

    instance_key = "diamond_instance_count"
    instance_count = contract_cache.get(instance_key, 0)
    contract_cache[instance_key] = instance_count + 1

    diamond_address = await create2_deploy(
        w3,
        deployer,
        get_initcode(
            DIAMOND_ARTIFACT["Diamond"], facets_in_constructor, deployer.address
        ),
        salt=DIAMOND_SALT_BASE + instance_count,
    )

    # register extra facets using diamondCut
    await IDiamondCut.fns.diamondCut(
        [loupe_cut, ownership_cut], ZERO_ADDRESS, b""
    ).transact(w3, deployer, to=diamond_address)

    return diamond_address, cut_address, loupe_address, ownership_address


async def test_diamond(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    deployer = ACCOUNTS["community"]

    diamond_address, cut_address, loupe_address, ownership_address = (
        await deploy_diamond(w3, deployer)
    )

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


async def test_add(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    deployer = ACCOUNTS["community"]
    diamond_address, *_ = await deploy_diamond(w3, deployer)
    greeter_address = await deploy_greeter(w3, deployer)
    facet_cut = FacetCut(greeter_address, FacetCutAction.ADD, GREETER_SELECTORS)
    await IDiamondCut.fns.diamondCut([facet_cut], ZERO_ADDRESS, b"").transact(
        w3, deployer, to=diamond_address
    )
    # verify facet was added
    facet_addresses = await IDiamondLoupe.fns.facetAddresses().call(
        w3, to=diamond_address
    )
    assert greeter_address.lower() in [addr.lower() for addr in facet_addresses]
    # test greeter functionality via diamond
    await set_and_verify_greeting(w3, deployer, diamond_address, "Hello from 💎")


async def test_replace(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    deployer = ACCOUNTS["community"]
    greeter_v1_address = await deploy_greeter(w3, deployer)
    greeter_v1_cut = FacetCut(greeter_v1_address, FacetCutAction.ADD, GREETER_SELECTORS)
    diamond_address, *_ = await deploy_diamond(
        w3, deployer, extra_facets=[greeter_v1_cut]
    )
    greeting_v1 = "Hello from v1"
    await set_and_verify_greeting(w3, deployer, diamond_address, greeting_v1)

    greeter_v2_address = await create2_deploy(
        w3,
        deployer,
        get_initcode(GREETER_ARTIFACT["Greeter"]),
        salt=V2_SALT,
    )
    greeter_v2_cut = FacetCut(
        greeter_v2_address, FacetCutAction.REPLACE, GREETER_SELECTORS
    )
    await IDiamondCut.fns.diamondCut([greeter_v2_cut], ZERO_ADDRESS, b"").transact(
        w3, deployer, to=diamond_address
    )
    # verify selector now points to v2
    await verify_facet_address(
        w3, diamond_address, IGreeter.fns.greet.selector, greeter_v2_address
    )
    # storage should be preserved (v1 unchanged)
    assert await IGreeter.fns.greet().call(w3, to=diamond_address) == greeting_v1


async def test_remove(mantra):
    w3: AsyncWeb3 = mantra.async_w3
    deployer = ACCOUNTS["community"]
    greeter_address = await deploy_greeter(w3, deployer)
    greeter_cut = FacetCut(greeter_address, FacetCutAction.ADD, GREETER_SELECTORS)
    diamond_address, *_ = await deploy_diamond(w3, deployer, extra_facets=[greeter_cut])

    greeting = "greeting"
    await set_and_verify_greeting(w3, deployer, diamond_address, greeting)

    # remove setGreeting function
    set_greeting_selector = IGreeter.fns.setGreeting.selector
    remove_cut = FacetCut(ZERO_ADDRESS, FacetCutAction.REMOVE, [set_greeting_selector])
    await IDiamondCut.fns.diamondCut([remove_cut], ZERO_ADDRESS, b"").transact(
        w3, deployer, to=diamond_address
    )
    # verify function was removed
    await verify_facet_address(w3, diamond_address, set_greeting_selector, ZERO_ADDRESS)
    with pytest.raises(Exception):
        await IGreeter.fns.setGreeting("fail").call(w3, to=diamond_address)
    assert await IGreeter.fns.greet().call(w3, to=diamond_address) == greeting

"""
https://eips.ethereum.org/EIPS/eip-2535
"""

from enum import IntEnum
from typing import NamedTuple

from eth_account.signers.base import BaseAccount
from eth_contract.contract import Contract
from eth_typing import ChecksumAddress
from web3 import AsyncWeb3
from web3.types import TxReceipt

from .utils import ZERO_ADDRESS

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


class FacetCutAction(IntEnum):
    ADD, REPLACE, REMOVE = range(3)


class FacetCut(NamedTuple):
    facet_address: str
    action: FacetCutAction
    function_selectors: list[bytes]


class Facet(NamedTuple):
    facet_address: str
    function_selectors: list[bytes]


async def build_diamond_cut(
    w3: AsyncWeb3, diamond: ChecksumAddress, facet: Facet
) -> list[FacetCut]:
    add = []
    replace = []
    remove = []
    old: str | None = None

    for sel in facet.function_selectors:
        existing = await IDiamondLoupe.fns.facetAddress(sel).call(w3, to=diamond)
        if existing == ZERO_ADDRESS:
            add.append(sel)
        elif existing.lower() != facet.facet_address.lower():
            replace.append(sel)
            old = existing

    if old is not None:
        old_selectors = await IDiamondLoupe.fns.facetFunctionSelectors(old).call(
            w3, to=diamond
        )
        new_selectors = set(facet.function_selectors)
        for old_sel in old_selectors:
            if old_sel not in new_selectors:
                remove.append(old_sel)

    return [
        FacetCut(facet_address=addr, action=action, function_selectors=selectors)
        for action, addr, selectors in (
            (FacetCutAction.REPLACE, facet.facet_address, replace),
            (FacetCutAction.REMOVE, ZERO_ADDRESS, remove),
            (FacetCutAction.ADD, facet.facet_address, add),
        )
        if selectors
    ]


async def cut_diamond(
    w3: AsyncWeb3, deployer: BaseAccount, diamond: ChecksumAddress, facet: Facet
) -> TxReceipt:
    cuts = await build_diamond_cut(w3, diamond, facet)
    return await IDiamondCut.fns.diamondCut(cuts, ZERO_ADDRESS, b"").transact(
        w3, deployer, to=diamond
    )

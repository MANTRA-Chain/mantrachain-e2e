// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.28;

import {IAnchoring} from "nvnm-contracts/IAnchoring.sol";

contract AnchoringConstructorCaller {
    IAnchoring internal constant ANCHORING =
        IAnchoring(0x0000000000000000000000000000000000000A00);

    bool public registryCreated;
    uint64 public createdRegistryId;

    constructor(string memory regName) {
        try ANCHORING.addRegistry(regName, "constructor bypass", "{}") returns (
            uint64 registryId
        ) {
            registryCreated = true;
            createdRegistryId = registryId;
        } catch {
            registryCreated = false;
            createdRegistryId = 0;
        }
    }
}

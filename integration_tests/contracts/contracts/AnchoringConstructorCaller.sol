// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.4;

interface IAnchoringPrecompileCtor {
    function addRegistry(
        string calldata name,
        string calldata description,
        string calldata metadata
    ) external returns (uint64 registryId);
}

contract AnchoringConstructorCaller {
    IAnchoringPrecompileCtor internal constant ANCHORING =
        IAnchoringPrecompileCtor(0x0000000000000000000000000000000000000A00);

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

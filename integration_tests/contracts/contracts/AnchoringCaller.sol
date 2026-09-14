// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.4;

interface IAnchoringPrecompile {
    struct Record {
        string uri;
        string checksum;
        string checksumAlgo;
        string metadata;
        string timestamp;
        string status;
        uint64 recordId;
        uint64 index;
        bool isLatest;
        uint64 registryId;
    }

    function addRegistry(
        string calldata name,
        string calldata description,
        string calldata metadata
    ) external returns (uint64 registryId);

    function addRecord(Record calldata record) external returns (uint64 recordId);

    function updateRecordStatus(
        uint64 registryId,
        uint64 recordId,
        uint64 index,
        string calldata status
    ) external;

    function grantRole(
        uint64 registryId,
        string calldata checksum,
        address account,
        string calldata role
    ) external;

    function revokeRole(
        uint64 registryId,
        string calldata checksum,
        address account,
        string calldata role
    ) external;

    struct Registry {
        uint64 id;
        string name;
        string description;
        string creator;
        string createdAt;
        string metadata;
    }

    struct PageRequest {
        bytes key;
        uint64 offset;
        uint64 limit;
        bool countTotal;
        bool reverse;
    }

    struct PageResponse {
        bytes nextKey;
        uint64 total;
    }

    function registriesByName(
        string calldata name,
        uint8 matchMode,
        PageRequest calldata pagination
    ) external returns (Registry[] memory, PageResponse memory);
}

contract AnchoringCaller {
    IAnchoringPrecompile internal constant ANCHORING =
        IAnchoringPrecompile(0x0000000000000000000000000000000000000A00);

    function _callAnchoring(bytes memory data) internal {
        (bool ok, bytes memory ret) = address(ANCHORING).call(data);
        if (ok) {
            return;
        }
        if (ret.length > 0) {
            assembly {
                revert(add(ret, 0x20), mload(ret))
            }
        }
        revert("sender not an eoa");
    }

    function callAddRegistry(
        string calldata name,
        string calldata description,
        string calldata metadata
    ) external returns (uint64 registryId) {
        bytes memory data = abi.encodeWithSelector(
            IAnchoringPrecompile.addRegistry.selector,
            name,
            description,
            metadata
        );
        (bool ok, bytes memory ret) = address(ANCHORING).call(data);
        if (!ok) {
            if (ret.length > 0) {
                assembly {
                    revert(add(ret, 0x20), mload(ret))
                }
            }
            revert("sender not an eoa");
        }
        registryId = abi.decode(ret, (uint64));
    }

    function callGrantRole(
        uint64 registryId,
        string calldata checksum,
        address account,
        string calldata role
    ) external {
        _callAnchoring(
            abi.encodeWithSelector(
                IAnchoringPrecompile.grantRole.selector,
                registryId,
                checksum,
                account,
                role
            )
        );
    }

    function callAddRecord(IAnchoringPrecompile.Record calldata record) external {
        _callAnchoring(
            abi.encodeWithSelector(IAnchoringPrecompile.addRecord.selector, record)
        );
    }

    function callUpdateRecordStatus(
        uint64 registryId,
        uint64 recordId,
        uint64 index,
        string calldata status
    ) external {
        _callAnchoring(
            abi.encodeWithSelector(
                IAnchoringPrecompile.updateRecordStatus.selector,
                registryId,
                recordId,
                index,
                status
            )
        );
    }

    function callRevokeRole(
        uint64 registryId,
        string calldata checksum,
        address account,
        string calldata role
    ) external {
        _callAnchoring(
            abi.encodeWithSelector(
                IAnchoringPrecompile.revokeRole.selector,
                registryId,
                checksum,
                account,
                role
            )
        );
    }

    // registriesByName is a view, but the precompile still refuses a contract
    // caller: its answer comes from a node-local index, so no contract may
    // build on it. Routed through call() rather than staticcall() so the
    // rejection is attributable to the EOA gate and not to write protection.
    function callRegistriesByName(
        string calldata name,
        uint8 matchMode
    ) external {
        _callAnchoring(
            abi.encodeWithSelector(
                IAnchoringPrecompile.registriesByName.selector,
                name,
                matchMode,
                IAnchoringPrecompile.PageRequest("", 0, 200, false, false)
            )
        );
    }
}

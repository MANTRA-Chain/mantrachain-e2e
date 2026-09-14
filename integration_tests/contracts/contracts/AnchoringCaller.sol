// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.28;

import {IAnchoring} from "nvnm-contracts/IAnchoring.sol";

contract AnchoringCaller {
    IAnchoring internal constant ANCHORING =
        IAnchoring(0x0000000000000000000000000000000000000A00);

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
            IAnchoring.addRegistry.selector,
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
                IAnchoring.grantRole.selector,
                registryId,
                checksum,
                account,
                role
            )
        );
    }

    function callAddRecord(IAnchoring.Record calldata record) external {
        _callAnchoring(
            abi.encodeWithSelector(IAnchoring.addRecord.selector, record)
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
                IAnchoring.updateRecordStatus.selector,
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
                IAnchoring.revokeRole.selector,
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
                IAnchoring.registriesByName.selector,
                name,
                matchMode,
                IAnchoring.PageRequest("", 0, 200, false, false)
            )
        );
    }
}

// SPDX-License-Identifier: MIT
pragma solidity ^0.8.21;

import "./DEXCallbackRouter.sol";

/**
 * @title DeFiVM
 * @notice Stateless executor for DeFi programs expressed as raw EVM bytecode.
 *         ``execute()`` DELEGATECALLs an EVM interpreter (Analog-Labs by
 *         default, custom address for chains/devnets where it is not
 *         pre-deployed) which interprets the program in DeFiVM's context.
 */
contract DeFiVM is DEXCallbackRouter {
    address private constant DEFAULT_INTERPRETER = 0x0000000000001e3F4F615cd5e20c681Cf7d85e8D;
    address private immutable INTERPRETER;

    constructor(address interpreter) {
        INTERPRETER = interpreter == address(0) ? DEFAULT_INTERPRETER : interpreter;
    }

    receive() external payable {}

    function execute(bytes calldata program) external payable {
        address interpreter = INTERPRETER;
        assembly {
            calldatacopy(0, program.offset, program.length)
            let ok := delegatecall(gas(), interpreter, 0, program.length, 0, 0)
            returndatacopy(0, 0, returndatasize())
            if iszero(ok) {
                revert(0, returndatasize())
            }
            return(0, returndatasize())
        }
    }
}

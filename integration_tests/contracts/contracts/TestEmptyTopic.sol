// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.4;

contract TestEmptyTopic {
    function test_log0() public {
        bytes32 data = "hello world";
        assembly {
            let p := mload(0x20)
            mstore(p, data)
            log0(p, 0x20)
        }
    }
}

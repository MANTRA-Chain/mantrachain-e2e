// SPDX-License-Identifier: LGPL-3.0-only
pragma solidity >=0.8.17;

contract ChainID {
    function currentChainID() public view returns (uint) {
        uint id;
        assembly {
            id := chainid()
        }
        return id;
    }
}

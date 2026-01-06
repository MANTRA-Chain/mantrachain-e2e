// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.4;

contract Coinbase {
    function getCurrentProposer() public view returns (address) {
        return block.coinbase;
    }
}

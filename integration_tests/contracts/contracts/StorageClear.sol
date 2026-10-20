// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.4;

// slot 0 starts non-zero so the first call takes the SSTORE clear refund
contract StorageClear {
    uint256 slot = 1;

    fallback() external {
        slot = 0;
    }
}

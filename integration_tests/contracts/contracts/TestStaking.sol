// SPDX-License-Identifier: MIT
pragma solidity ^0.8.4;

contract TestStaking {
    address constant precompile = 0x0000000000000000000000000000000000000800;
    address public account;

    function callDelegate(
        string memory validatorAddress,
        uint256 amount
    ) public payable returns (bool) {
        require(
            account == address(0) || account == msg.sender,
            "unauthorized caller"
        );
        (bool success, bytes memory data) = precompile.call(
            abi.encodeWithSignature(
                "delegate(address,string,uint256)",
                address(this),
                validatorAddress,
                amount
            )
        );
        require(success, "delegate precompile call failed");
        bool result = abi.decode(data, (bool));
        require(result, "delegate returned false");
        account = msg.sender;
        return true;
    }
}

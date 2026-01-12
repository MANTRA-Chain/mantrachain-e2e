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

    function callUndelegate(
        string memory validatorAddress,
        uint256 amount
    ) public returns (bool) {
        require(account == msg.sender, "unauthorized caller");
        (bool success, bytes memory data) = precompile.call(
            abi.encodeWithSignature(
                "undelegate(address,string,uint256)",
                address(this),
                validatorAddress,
                amount
            )
        );
        require(success, "undelegate precompile call failed");
        int64 completionTime = abi.decode(data, (int64));
        require(completionTime > 0, "undelegate returned invalid time");
        return true;
    }

    function callRedelegate(
        string memory validatorSrcAddress,
        string memory validatorDstAddress,
        uint256 amount
    ) public returns (bool) {
        require(account != address(0), "no delegation exists");
        require(account == msg.sender, "unauthorized caller");
        (bool success, bytes memory data) = precompile.call(
            abi.encodeWithSignature(
                "redelegate(address,string,string,uint256)",
                address(this),
                validatorSrcAddress,
                validatorDstAddress,
                amount
            )
        );
        require(success, "redelegate precompile call failed");
        int64 completionTime = abi.decode(data, (int64));
        require(completionTime > 0, "redelegate returned invalid time");
        return true;
    }
}

// SPDX-License-Identifier: UNLICENSED 
pragma solidity ^0.8.13;

contract Minimal {
    function killMe() public payable {
        selfdestruct(payable(address(this)));
    }
}

contract Selfdestruct {
    event ContractCreated(address indexed);

    function exploit() public payable {
        Minimal minimal = new Minimal();
        minimal.killMe{value: msg.value}();
        emit ContractCreated(address(minimal));
    }
}

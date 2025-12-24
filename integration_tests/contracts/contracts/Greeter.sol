// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.4;

contract Greeter {
    uint public n;
    string public greeting;

    event ChangeGreeting(address from, string value);

    constructor() {
        greeting = "Hello";
    }

    function setGreeting(string memory _greeting) public {
        greeting = _greeting;
        emit ChangeGreeting(msg.sender, _greeting);
    }

    function greet() public view returns (string memory) {
        return greeting;
    }

    function intValue() public view returns (uint) {
        return n;
    }

    function toRemove() pure public returns (string memory) {
        return "toRemove";
    }
}

contract GreeterV2 {
    // replace
    function greet() public pure returns (string memory) {
        return "hello from v2";
    }

    // add
    function newMethod() public pure returns (string memory) {
        return "newMethod";
    }

}

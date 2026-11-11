// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract Calculator {
    uint public x = 20;
    uint public y = 20;

    function getSum() public view returns (uint256) {
        return x + y;
    }
}

contract Caller {
    Calculator calculator;

    constructor(address _calc) {
        calculator = Calculator(_calc);
    }

    // a STATICCALL into the calculator
    function callCalculator() public view returns (uint sum) {
        sum = calculator.getSum();
    }
}

// SPDX-License-Identifier: MIT
pragma solidity ^0.8.4;

// Just enough ERC20 for x/erc20 to register and convert. Its transfer, run as
// x/erc20's internal EVM call, burns all but 200k of the gas it is given (the
// rest covers the commit's own store gas) and pays 1 wei to a blocked module
// account, so that call's statedb commit fails.
contract GreedyToken {
    // the x/erc20 module account, sha256("erc20")[:20]
    address constant ERC20_MODULE = 0x47EeB2eac350E1923b8CBDfA4396A077b36E62a0;

    string public constant name = "Greedy";
    string public constant symbol = "GRDY";
    uint8 public constant decimals = 18;

    receive() external payable {}

    function balanceOf(address) external pure returns (uint256) {
        return 0;
    }

    function transfer(address, uint256) external returns (bool) {
        payable(ERC20_MODULE).transfer(1);
        while (gasleft() > 200_000) {}
        return true;
    }
}

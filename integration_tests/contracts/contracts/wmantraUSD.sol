// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

contract wmantraUSD is ERC20 {
    using SafeERC20 for IERC20;

    IERC20 public immutable mantraUSD;
    uint256 private constant SCALAR = 10**12; // 10^18 / 10^6

    constructor(address _mantrausdAddress) ERC20("Wrapped mantraUSDC", "wmantraUSD") {
        require(_mantrausdAddress != address(0), "Invalid address");
        mantraUSD = IERC20(_mantrausdAddress);
    }

    // Note: bridging (x/erc20 convert + ICS20 transfer) is handled by the frontend
    // calling the relevant precompiles directly.

    /**
     * @dev Deposit mantraUSD (6 decimals) -> Mint wmantraUSD (18 decimals)
     */
    function deposit(uint256 amountMantraUSD) external {
        require(amountMantraUSD > 0, "Amount must be greater than 0");

        mantraUSD.safeTransferFrom(msg.sender, address(this), amountMantraUSD);
        
        // Scale up
        uint256 amountToMint = amountMantraUSD * SCALAR;
        _mint(msg.sender, amountToMint);
        
        emit Deposit(msg.sender, amountMantraUSD);
    }

    /**
     * @dev Withdraw wmantraUSD -> mantraUSD. 
     * If the user inputs an amount with dust (e.g., 1.000000000001), 
     * we only burn the clean 1.0 part and leave the dust in their wallet.
     */
    function withdraw(uint256 amountWmantraUSD) external {
        require(balanceOf(msg.sender) >= amountWmantraUSD, "Insufficient balance");

        // 1. Calculate the clean mantraUSD amount (Integer division handles the truncation)
        uint256 mantraUSDToReturn = amountWmantraUSD / SCALAR;
        require(mantraUSDToReturn > 0, "Amount too small to withdraw");

        // 2. Calculate the exact wmantraUSD amount required for that mantraUSD
        // Any remainder from the input `amountWmantraUSD` is ignored and not burned.
        uint256 wmantraUSDToBurn = mantraUSDToReturn * SCALAR;

        // 3. Burn only the convertable part
        _burn(msg.sender, wmantraUSDToBurn);
        // 4. Send the mantraUSD
        mantraUSD.safeTransfer(msg.sender, mantraUSDToReturn);

        emit Withdrawal(msg.sender, mantraUSDToReturn);
    }

    event Deposit(address indexed user, uint256 mantraUSDAmount);
    event Withdrawal(address indexed user, uint256 mantraUSDAmount);
}
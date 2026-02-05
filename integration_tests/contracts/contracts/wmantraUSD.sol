// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/token/ERC20/extensions/ERC20Wrapper.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

contract wmantraUSD is ERC20, ERC20Wrapper {
    uint256 private constant SCALAR = 10 ** 12; // 10^18 / 10^6

    event Deposit(
        address sender,
        address indexed account,
        uint256 depositedValue,
        uint256 mintedValue
    );
    event Withdrawal(
        address sender,
        address indexed account,
        uint256 withdrawValue,
        uint256 burnedValue
    );

    constructor(
        IERC20 underlyingToken
    ) ERC20("Wrapped mantraUSD", "wmantraUSD") ERC20Wrapper(underlyingToken) {}

    function decimals()
        public
        view
        virtual
        override(ERC20, ERC20Wrapper)
        returns (uint8)
    {
        return 18;
    }

    /**
     * @dev Allow a user to deposit underlying tokens and mint the corresponding number of wrapped tokens.
     */
    function depositFor(
        address account,
        uint256 value
    ) public virtual override returns (bool) {
        address sender = _msgSender();
        if (sender == address(this)) {
            revert ERC20InvalidSender(address(this));
        }
        if (account == address(this)) {
            revert ERC20InvalidReceiver(account);
        }
        SafeERC20.safeTransferFrom(
            this.underlying(),
            sender,
            address(this),
            value
        );
        // Scale up
        uint256 amountToMint = value * SCALAR;
        _mint(account, amountToMint);
        emit Deposit(sender, account, value, amountToMint);
        return true;
    }

    /**
     * @dev Allow a user to burn a number of wrapped tokens and withdraw the corresponding number of underlying tokens.
     */
    function withdrawTo(
        address account,
        uint256 value
    ) public virtual override returns (bool) {
        if (account == address(this)) {
            revert ERC20InvalidReceiver(account);
        }
        address sender = _msgSender();

        require(balanceOf(sender) >= value, "Insufficient balance");

        // 1. Calculate the clean mantraUSD amount (Integer division handles the truncation)
        uint256 mantraUSDToReturn = value / SCALAR;
        require(mantraUSDToReturn > 0, "Amount too small to withdraw");

        // 2. Calculate the exact wmantraUSD amount required for that mantraUSD
        // Any remainder from the input `amountWmantraUSD` is ignored and not burned.
        uint256 wmantraUSDToBurn = mantraUSDToReturn * SCALAR;
        _burn(sender, wmantraUSDToBurn);

        // 3. Send the underlying token
        SafeERC20.safeTransfer(this.underlying(), account, mantraUSDToReturn);
        emit Withdrawal(sender, account, mantraUSDToReturn, wmantraUSDToBurn);
        return true;
    }
}

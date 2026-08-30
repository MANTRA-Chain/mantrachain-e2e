// SPDX-License-Identifier: MIT
pragma solidity ^0.8.21;

/**
 * @title DEXCallbackRouter
 * @notice Mixin that answers V2/V3 DEX swap callbacks for the inheriting
 *         contract.  Inherited by ``DeFiVM`` so flash-swap programs can
 *         return calldata to the originating pool without bespoke logic
 *         in each composer.  See the upstream
 *         (https://github.com/yihuang/pydefi) source for the data-encoding
 *         conventions and the supported selector list.
 */
abstract contract DEXCallbackRouter {
    bytes4 private constant SEL_V3_CALLBACK      = 0xfa461e33;
    bytes4 private constant SEL_ALGEBRA_CALLBACK = 0x2c8958f6;
    bytes4 private constant SEL_PANCAKE_V3       = 0x23a69e75;
    bytes4 private constant SEL_SOLIDLY_V3       = 0x3a1c453c;
    bytes4 private constant SEL_V2_CALLBACK      = 0x10d1e85c;
    bytes4 private constant SEL_AERODROME_HOOK   = 0x9a7bff79;
    bytes4 private constant SEL_RAMSES_V2        = 0xde5f4ecc;
    bytes4 private constant TRANSFER_SEL         = 0xa9059cbb;

    fallback() external virtual {
        bytes4 sel;
        assembly {
            sel := calldataload(0)
        }

        if (
            sel == SEL_V3_CALLBACK ||
            sel == SEL_ALGEBRA_CALLBACK ||
            sel == SEL_PANCAKE_V3 ||
            sel == SEL_SOLIDLY_V3
        ) {
            int256 amount0Delta;
            int256 amount1Delta;
            address tokenIn;
            assembly {
                amount0Delta := calldataload(4)
                amount1Delta := calldataload(36)
                let dataRelOff := calldataload(68)
                tokenIn := calldataload(add(add(4, dataRelOff), 32))
            }
            int256 amount = amount0Delta > 0 ? amount0Delta : amount1Delta;
            if (amount > 0) {
                _callTransfer(tokenIn, msg.sender, uint256(amount));
            }
        } else if (sel == SEL_V2_CALLBACK || sel == SEL_AERODROME_HOOK) {
            address tokenIn;
            uint256 amountOwed;
            assembly {
                let dataRelOff := calldataload(100)
                let dataStart  := add(add(4, dataRelOff), 32)
                tokenIn    := calldataload(dataStart)
                amountOwed := calldataload(add(dataStart, 32))
            }
            if (amountOwed > 0) {
                _callTransfer(tokenIn, msg.sender, amountOwed);
            }
        } else if (sel == SEL_RAMSES_V2) {
            address tokenIn;
            uint256 amountOwed;
            assembly {
                let dataRelOff := calldataload(68)
                let dataStart  := add(add(4, dataRelOff), 32)
                tokenIn    := calldataload(dataStart)
                amountOwed := calldataload(add(dataStart, 32))
            }
            if (amountOwed > 0) {
                _callTransfer(tokenIn, msg.sender, amountOwed);
            }
        } else {
            revert("DEXCallbackRouter: unknown callback selector");
        }
    }

    function _callTransfer(address token, address to, uint256 amount) internal {
        (bool ok, bytes memory ret) = token.call(abi.encodeWithSelector(TRANSFER_SEL, to, amount));
        require(ok && (ret.length == 0 || abi.decode(ret, (bool))), "DEXCallbackRouter: transfer failed");
    }
}

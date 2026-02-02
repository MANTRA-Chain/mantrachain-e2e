// SPDX-License-Identifier: LGPL-3.0-only
pragma solidity >=0.8.17;

/// @dev The DistributionClaimI precompile contract address.
address constant DISTRIBUTION_CLAIM_PRECOMPILE_ADDRESS = 0x0000000000000000000000000000000000000a01;

/// @title Mantrachain Distribution Claim Precompile
/// @dev Simplified flow: claim rewards and convert a specified coin denom into its ERC20 representation.
/// @custom:address 0x0000000000000000000000000000000000000a01
interface DistributionClaimI {
    /// @dev Claims rewards from up to `maxRetrieve` delegated validators, then converts the claimed amount for `denom`
    /// into its ERC20 representation via x/erc20.
    ///
    /// Requirements:
    /// - `delegatorAddress` must be the transaction sender.
    ///
    /// @param delegatorAddress The delegator EVM address.
    /// @param maxRetrieve Maximum number of validators to claim from.
    /// @param denom Coin denom to convert (e.g. "amantra" or "erc20:<addr>").
    /// @return convertedAmount Amount converted (in coin base units).
    function claimRewardsAndConvertCoin(
        address delegatorAddress,
        uint32 maxRetrieve,
        string memory denom
    ) external returns (uint256 convertedAmount);
}

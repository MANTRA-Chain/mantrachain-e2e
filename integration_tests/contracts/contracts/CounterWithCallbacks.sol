// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.4;

import "./ICallbacks.sol";
import "./ICS20I.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";

contract CounterWithCallbacks is ICallbacks {
    // State variables
    int public counter;

    // Mapping: user address => token address => balance
    mapping(address => mapping(address => uint256)) public userTokenBalances;

    // Events
    event CounterIncremented(int newValue, address indexed user);
    event TokensDeposited(
        address indexed user,
        address indexed token,
        uint256 amount,
        uint256 newBalance
    );
    event PacketAcknowledged(
        string indexed channelId,
        string indexed portId,
        uint64 sequence,
        bytes data,
        bytes acknowledgement
    );
    event PacketTimedOut(
        string indexed channelId,
        string indexed portId,
        uint64 sequence,
        bytes data
    );

    event IBCTransferSent(uint64 sequence);
    struct NestedAckForwardConfig {
        string sourcePort;
        string sourceChannel;
        string denom;
        uint256 amount;
        string receiver;
        Height timeoutHeight;
        uint64 timeoutTimestamp;
        string memo;
    }

    NestedAckForwardConfig private nestedAckForwardCfg;
    bool public nestedAckForwardEnabled;
    bool public nestedAckForwardAttempted;
    bool public nestedAckForwardSucceeded;
    uint64 public nestedAckForwardSequence;

    /**
     * @dev Increment the counter and deposit ERC20 tokens
     * @param token The address of the ERC20 token
     * @param amount The amount of tokens to deposit
     */
    function add(address token, uint256 amount)
    external
    {
        // Transfer tokens from user to this contract
        IERC20(token).transferFrom(msg.sender, address(this), amount);

        // Increment counter
        counter += 1;

        // Add to user's token balance
        userTokenBalances[msg.sender][token] += amount;

        // Emit events
        emit CounterIncremented(counter, msg.sender);
        emit TokensDeposited(msg.sender, token, amount, userTokenBalances[msg.sender][token]);
    }

    /**
     * @dev Get the current counter value
     * @return The current counter value
     */
    function getCounter() external view returns (int) {
        return counter;
    }

    /**
     * @dev Get a user's balance for a specific token
     * @param user The address of the user
     * @param token The address of the token
     * @return The user's token balance
     */
    function getTokenBalance(address user, address token) external view returns (uint256) {
        return userTokenBalances[user][token];
    }

    /**
     * @dev Implementation of ICallbacks interface
     * Called when a packet acknowledgement is received
     */
    function onPacketAcknowledgement(
        string memory channelId,
        string memory portId,
        uint64 sequence,
        bytes memory data,
        bytes memory acknowledgement
    ) external override {
        // Emit event when packet is acknowledged
        emit PacketAcknowledged(channelId, portId, sequence, data, acknowledgement);

        if (nestedAckForwardEnabled) {
            nestedAckForwardAttempted = true;
            try ICS20_CONTRACT.transfer(
                nestedAckForwardCfg.sourcePort,
                nestedAckForwardCfg.sourceChannel,
                nestedAckForwardCfg.denom,
                nestedAckForwardCfg.amount,
                address(this),
                nestedAckForwardCfg.receiver,
                nestedAckForwardCfg.timeoutHeight,
                nestedAckForwardCfg.timeoutTimestamp,
                nestedAckForwardCfg.memo
            ) returns (uint64 nextSequence) {
                nestedAckForwardSucceeded = true;
                nestedAckForwardSequence = nextSequence;
            } catch {
                nestedAckForwardSucceeded = false;
                nestedAckForwardSequence = 0;
            }
        }

        counter += 1; // Increment counter on acknowledgement
    }

    /**
     * @dev Implementation of ICallbacks interface
     * Called when a packet times out
     */
    function onPacketTimeout(
        string memory channelId,
        string memory portId,
        uint64 sequence,
        bytes memory data
    ) external override {
        // Emit event when packet times out
        emit PacketTimedOut(channelId, portId, sequence, data);
        counter -= 1; // Decrement counter on timeout
    }

    /**
     * @dev Reset the counter
     */
    function resetCounter() external {
        counter = 0;
    }

    function configureNestedAckForward(
        string memory sourcePort,
        string memory sourceChannel,
        string memory denom,
        uint256 amount,
        string memory receiver,
        Height memory timeoutHeight,
        uint64 timeoutTimestamp,
        string memory memo
    ) external {
        nestedAckForwardCfg = NestedAckForwardConfig({
            sourcePort: sourcePort,
            sourceChannel: sourceChannel,
            denom: denom,
            amount: amount,
            receiver: receiver,
            timeoutHeight: timeoutHeight,
            timeoutTimestamp: timeoutTimestamp,
            memo: memo
        });
        nestedAckForwardEnabled = true;
        nestedAckForwardAttempted = false;
        nestedAckForwardSucceeded = false;
        nestedAckForwardSequence = 0;
    }

    function disableNestedAckForward() external {
        nestedAckForwardEnabled = false;
    }

    function ibcTransfer(
        string memory sourcePort,
        string memory sourceChannel,
        string memory denom,
        uint256 amount,
        string memory receiver,
        Height memory timeoutHeight,
        uint64 timeoutTimestamp,
        string memory memo
    ) external returns (uint64 nextSequence) {
        nextSequence = ICS20_CONTRACT.transfer(
            sourcePort,
            sourceChannel,
            denom,
            amount,
            address(this),
            receiver,
            timeoutHeight,
            timeoutTimestamp,
            memo
        );
        emit IBCTransferSent(nextSequence);
    }
}
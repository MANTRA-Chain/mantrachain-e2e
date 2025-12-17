// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// @title DocumentI
/// @dev Interface for the document precompile contract
interface DocumentI {
    /// @dev Document struct definition
    struct Document {
        string name;
        string denom;
        string uri;
        string checksum;
        string checksumAlgo;
        string timestamp;
        string figi;
        string individualId;
    }

    /// @dev PageRequest struct for pagination
    struct PageRequest {
        bytes key;
        uint64 offset;
        uint64 limit;
        bool countTotal;
        bool reverse;
    }

    /// @dev PageResponse struct for pagination response
    struct PageResponse {
        bytes nextKey;
        uint64 total;
    }

    /// @dev Adds a document to a registry
    /// @param document The document struct containing document metadata
    function addDocument(Document memory document) external;

    /// @dev Removes a document from a registry
    /// @param denom The registry denom
    /// @param index The index of the document to remove
    function removeDocument(string memory denom, uint64 index) external;

    /// @dev Queries documents from a registry
    /// @param denom The registry denom
    /// @param index The document index
    /// @param pagination The pagination parameters
    /// @return documents The list of documents
    /// @return paginationResponse The pagination response
    function documents(
        string memory denom,
        uint64 index,
        PageRequest memory pagination
    ) external view returns (Document[] memory documents, PageResponse memory paginationResponse);

    /// @dev Grants a role to an account
    /// @param registryId The ID of the registry
    /// @param checksum The document checksum (empty string for registry-level roles)
    /// @param account The address to grant the role to
    /// @param role The role to grant
    function grantRole(
        uint64 registryId,
        string memory checksum,
        address account,
        string memory role
    ) external;

    /// @dev Revokes a role from an account
    /// @param registryId The ID of the registry
    /// @param checksum The document checksum (empty string for registry-level roles)
    /// @param account The address to revoke the role from
    function revokeRole(
        uint64 registryId,
        string memory checksum,
        address account
    ) external;
}

# Mantrachain E2E Integration Tests

This repository contains end-to-end integration tests for the MANTRA Chain project, focusing on Cosmos/EVM compatibility, transaction flows, and protocol upgrades.

## Structure

- `integration_tests/`: Python tests for various flows and protocol features.
- `scripts/`: Shell scripts for starting nodes, generating genesis files, and managing test environments.
- `nix/`: Nix expressions for reproducible builds and test environments.

## Usage

### Prerequisites

- [Nix](https://nixos.org/download.html) installed

### Running Tests

1. **Build environment and dependencies:**
   ```sh
   nix-shell integration_tests/shell.nix 
   ```

2. **Generate genesis files (if needed):**
   ```sh
    prysmctl testnet generate-genesis \
    --num-validators=1 \
    --chain-config-file=config.yaml \
    --geth-genesis-json-in=../scripts/geth-genesis.json \
    --geth-genesis-json-out=../scripts/geth-genesis.json \
    --fork=electra \
    --output-ssz=genesis.ssz
   ```

3. **Run tests:**
   to try all test
   ```sh
   make test-e2e-nix
   ```
   or specific marker
   ```sh
   pytest -vv -s -m asyncio
   pytest -vv -s -m unmarked
   pytest -vv -s -m slow
   ```
   or more specific
   ```sh
   pytest -vv -s test_basic.py::test_multisig
   ```

### Nix Build Targets

- Build mantrachain for a specific platform:
  ```sh
  nix build .#legacyPackages.aarch64-darwin.mantrachain
  nix build .#legacyPackages.aarch64-linux.mantrachain
  ```

## Key Test Files

- `test_flow.py`: Tests Cosmos/EVM transfer flows and balance assertions.
- `test_eip1559.py`: Tests EIP-1559 dynamic fee transactions and base fee adjustment.
- `test_eip7702.py`: Tests EIP-7702 account abstraction and related flows.
- `test_subscribe.py`: Tests websocket subscriptions and log/event streaming.
- `test_upgrade.py`: Tests cosmovisor-based binary upgrades and verifies chain functionality before and after upgrade.
- `test_fee_history.py`: Tests eth_feeHistory with various scenarios including concurrent requests, parameter changes, and edge cases like beyond-head blocks and invalid percentiles.
- `test_contract.py`: Tests deploy contract with create2 create3 and multicall.
- `test_ibc.py`: Tests cross-chain transaction in IBC.

## Configuration

- `integration_tests/config.yaml`: Beacon chain and fork configuration.

## Notes

- Some tests are skipped by default (see `@pytest.mark.skip`) and can be enabled as needed.
- Ensure all paths to config files are correct in scripts and Nix expressions.
- For troubleshooting, check logs in the respective data directories and review script outputs.

---

For more details, see comments in each script and test file.
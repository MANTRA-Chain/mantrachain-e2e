import os
import subprocess
from pathlib import Path

import pytest

from .utils import DEFAULT_DENOM

pytestmark = pytest.mark.wasm


def test_wasm(mantra):
    # Set up environment variables
    env = os.environ.copy()

    cli = mantra.cosmos_cli()
    chain_obj = mantra
    # For local/ci tests, use SIGNER1_MNEMONIC
    env["SEED_PHRASE"] = os.getenv("SIGNER1_MNEMONIC")

    # Extract connection parameters
    rpc = cli.node_rpc
    chain_id = cli.chain_id
    denom = DEFAULT_DENOM
    binary = chain_obj.chain_binary  # Get binary from the appropriate object

    # Path to the test script
    script_path = Path(__file__).parent.parent / "scripts" / "test_ci.sh"

    # Build the command
    cmd = [str(script_path), "-r", rpc, "-c", chain_id, "-d", denom, "-b", binary]

    # Add wallet parameter only if it exists
    if hasattr(chain_obj, "wallet") and chain_obj.wallet:
        cmd.extend(["-w", chain_obj.wallet])

    print(f"Running test_ci.sh with args: {' '.join(cmd)}")
    print(f"RPC: {rpc}, Chain ID: {chain_id}, Denom: {denom}, Binary: {binary}")

    # Run the script
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)

    # Print output for debugging
    if result.stdout:
        print("STDOUT:", result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)

    # Check if the script succeeded (return code 0)
    assert (
        result.returncode == 0
    ), f"test_ci.sh failed with return code {result.returncode}"

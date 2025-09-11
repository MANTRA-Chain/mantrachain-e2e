import os
import subprocess

import pytest

from .utils import find_log_event_attrs

pytestmark = pytest.mark.wasm


def test_wasm(mantra):
    cli = mantra.cosmos_cli()
    name = "signer1"
    wallet = cli.address(name)

    # Compiling smart contracts
    res = subprocess.run(
        [os.path.join("scripts", "build_release.sh")], capture_output=True, text=True
    )
    assert res.returncode == 0, f"Contract compilation failed\n{res.stderr}"

    CONTRACT_DIR = "artifacts"
    wasm_files = [f for f in os.listdir(CONTRACT_DIR) if f.endswith(".wasm")]
    assert wasm_files, "No WASM files found"

    code_ids = []
    for contract in wasm_files:
        print(f"Uploading contract: {contract}")
        res = cli.wasm_store(
            os.path.join(CONTRACT_DIR, contract),
            wallet,
            _from=name,
            gas=2500000,
        )
        attr = "code_id"
        code_id = find_log_event_attrs(
            res["events"], "store_code", lambda attrs: attr in attrs
        ).get(attr)
        code_ids.append(code_id)

    print(f"All contracts uploaded. Code IDs: {code_ids}")

    contract_addresses = []
    for code_id in code_ids:
        print(f"Instantiating contract with code_id {code_id}")
        res = cli.wasm_instantiate(code_id, wallet, _from=name, gas=2500000)
        attr = "_contract_address"
        contract_address = find_log_event_attrs(
            res["events"], "instantiate", lambda attrs: attr in attrs
        ).get(attr)
        contract_addresses.append(contract_address)

    print(f"All contracts instantiated. Addresses: {contract_addresses}")

import os
import subprocess

import pytest

from .utils import DEFAULT_DENOM, find_log_event_attrs

pytestmark = pytest.mark.wasm


def test_wasm(mantra):
    cli = mantra.cosmos_cli()
    name = "signer1"
    wallet = cli.address(name)
    gas = 2500000

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
            gas=gas,
        )
        attr = "code_id"
        code_id = find_log_event_attrs(
            res["events"], "store_code", lambda attrs: attr in attrs
        ).get(attr)
        code_ids.append(code_id)

    print(f"All contracts uploaded. Code IDs: {code_ids}")

    contract_addresses = []
    for code_id in code_ids:
        print(f"Instantiating contract with code_id {code_id} twice")
        for i in range(2):
            res = cli.wasm_instantiate(
                code_id, wallet, _from=name, gas=gas, label="test"
            )
            attr = "_contract_address"
            contract_address = find_log_event_attrs(
                res["events"], "instantiate", lambda attrs: attr in attrs
            ).get(attr)
            print(f"Instantiated contract {i} at: {contract_address}")
            contract_addresses.append(contract_address)

    print(f"All contracts instantiated. Addresses: {contract_addresses}")

    # Testing instantiation with unauthorized wallet (should fail)
    unauthorized = "signer2"
    unauthorized_wallet = cli.address(unauthorized)
    res = cli.wasm_instantiate(
        code_ids[0], unauthorized_wallet, _from=unauthorized, gas=gas, label="test_fail"
    )
    assert res["code"] != 0
    assert "can not instantiate: unauthorized" in res["raw_log"]

    # Testing contract executions
    contract0 = contract_addresses[0]
    contract1 = contract_addresses[1]
    amt = f"10{DEFAULT_DENOM}"

    def execute_tx(msg, amount=None, gas_limit=gas, success=True):
        res = (
            cli.wasm_execute(contract0, msg, amount, _from=name, gas=gas_limit)
            if amount
            else cli.wasm_execute(contract0, msg, _from=name, gas=gas_limit)
        )
        assert (res["code"] == 0) if success else (res["code"] != 0)

    execute_tx({"modify_state": {}})
    execute_tx({"send_funds": {"receipient": contract1}}, amt)
    execute_tx({"send_funds": {"receipient": contract1}}, success=False)
    execute_tx({"call_contract": {"contract": contract1, "reply": True}}, amt)
    execute_tx({"call_contract": {"contract": contract1, "reply": False}}, amt)
    execute_tx({"delete_entry_on_map": {"key": 1}})
    execute_tx({"fill_map": {"limit": 100}})
    execute_tx({"fill_map": {"limit": 1010}}, gas_limit=4000000)
    execute_tx({"fill_map": {"limit": 1000000000000}}, success=False)
    execute_tx({"invalid": {}}, success=False)

    # Query contract
    queries = [
        {"get_count": {}},
        {"iterate_over_map": {"limit": 5}},
        {"iterate_over_map": {"limit": 500}},
        {"get_entry_from_map": {"entry": 1}},
        {"get_entry_from_map": {"entry": 250}},
    ]
    for query_msg in queries:
        assert "data" in cli.query_wasm_contract_state(contract0, query_msg)

    assert "data" in cli.query_wasm_contract_state(contract0, "Y291bnQ=", cmd="raw")

    # Test migration
    res = cli.wasm_migrate(contract0, code_ids[0], {}, _from=name, gas=gas)
    assert res["code"] == 0
    res = cli.wasm_migrate(contract0, code_ids[0], {}, _from=unauthorized, gas=gas)
    assert res["code"] != 0
    assert "can not migrate: unauthorized" in res["raw_log"]

    # Test second contract
    queries = [
        {"get_count": {}},
        {"iterate_over_map": {"limit": 5}},
        {"iterate_over_map": {"limit": 500}},
        {"iterate_over_map": {"limit": 1001}},
    ]
    for query_msg in queries:
        assert "data" in cli.query_wasm_contract_state(contract1, query_msg)

    for entry in [1, 250]:
        with pytest.raises(AssertionError, match="not found"):
            cli.query_wasm_contract_state(
                contract1, {"get_entry_from_map": {"entry": entry}}
            )

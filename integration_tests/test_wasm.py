from pathlib import Path

import pytest

from .utils import DEFAULT_DENOM, find_log_event_attrs


def test_wasm(mantra):
    cli = mantra.cosmos_cli()
    name = "signer1"
    wallet = cli.address(name)
    gas = 2500000

    contract = Path(__file__).parent / "contracts/contracts/contract_1.wasm"
    res = cli.wasm_store(
        str(contract),
        wallet,
        _from=name,
        gas=gas,
    )
    assert res["code"] == 0
    attr = "code_id"
    code_id = find_log_event_attrs(
        res["events"], "store_code", lambda attrs: attr in attrs
    ).get(attr)

    print(f"All contracts uploaded. Code IDs: {code_id}")

    contract_addresses = []
    print(f"Instantiating contract with code_id {code_id} twice")
    for i in range(2):
        res = cli.wasm_instantiate(code_id, wallet, _from=name, gas=gas)
        assert res["code"] == 0
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
        code_id, unauthorized_wallet, _from=unauthorized, gas=gas, label="test_fail"
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
    res = cli.wasm_migrate(contract0, code_id, {}, _from=name, gas=gas)
    assert res["code"] == 0
    res = cli.wasm_migrate(contract0, code_id, {}, _from=unauthorized, gas=gas)
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

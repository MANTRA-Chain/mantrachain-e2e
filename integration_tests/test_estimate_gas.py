import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from .utils import (
    Contract,
    RevertTestContract,
    create_contract_transaction,
)

METHOD = "eth_estimateGas"


def test_revert(mantra):
    def process(w3):
        revert = RevertTestContract("TestRevert")
        revert.deploy(w3)
        contract = revert.contract
        res = []
        call = w3.provider.make_request
        # revertWithoutMsg
        data = "0x9ffb86a5"
        params = {"to": contract.address, "data": data}
        rsp = call(METHOD, [params])
        error = rsp["error"]
        assert error["code"] == 3
        assert error["message"] == "execution reverted: Function has been reverted"
        assert (
            error["data"]
            == "0x08c379a00000000000000000000000000000000000000000000000000000000000000020000000000000000000000000000000000000000000000000000000000000001a46756e6374696f6e20686173206265656e207265766572746564000000000000"  # noqa: E501
        )
        res = [json.dumps(error, sort_keys=True)]
        return res

    providers = [mantra.w3]
    with ThreadPoolExecutor(len(providers)) as exec:
        tasks = [exec.submit(process, w3) for w3 in providers]
        res = [future.result() for future in as_completed(tasks)]
        assert len(res) == len(providers)
        assert res[0] == res[-1], res


def test_out_of_gas_error(mantra):
    iterations = 1
    gas = 21204

    def process(w3):
        msg = Contract("TestMessageCall")
        msg.deploy(w3)
        contract = msg.contract
        tx = contract.functions.test(iterations).build_transaction()
        tx = {"to": contract.address, "data": tx["data"], "gas": hex(gas)}
        call = w3.provider.make_request
        error = call(METHOD, [tx])["error"]
        assert error["code"] == -32000
        assert f"gas required exceeds allowance ({gas})" in error["message"]

    providers = [mantra.w3]
    with ThreadPoolExecutor(len(providers)) as exec:
        tasks = [exec.submit(process, w3) for w3 in providers]
        res = [future.result() for future in as_completed(tasks)]
        assert len(res) == len(providers)


def test_storage_out_of_gas_error(mantra):
    gas = 210000

    def process(w3):
        tx = create_contract_transaction(w3, "TestMessageCall")
        tx = {"data": tx["data"], "gas": hex(gas)}
        call = w3.provider.make_request
        error = call(METHOD, [tx])["error"]
        assert error["code"] == -32000
        assert "contract creation code storage out of gas" in error["message"]

    providers = [mantra.w3]
    with ThreadPoolExecutor(len(providers)) as exec:
        tasks = [exec.submit(process, w3) for w3 in providers]
        res = [future.result() for future in as_completed(tasks)]
        assert len(res) == len(providers)

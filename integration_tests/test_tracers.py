import asyncio
import os

import pytest
from eth_contract.create2 import CREATE2_FACTORY, create2_address
from eth_contract.deploy_utils import (
    ensure_create2_deployed,
    ensure_deployed_by_create2,
    ensure_multicall3_deployed,
)
from eth_contract.erc20 import ERC20
from eth_contract.multicall3 import MULTICALL3, MULTICALL3_ADDRESS, Call3
from eth_contract.utils import get_initcode

from .expected_constants import (
    EXPECTED_CALLTRACERS,
    EXPECTED_CONTRACT_CREATE_TRACER,
    EXPECTED_STRUCT_TRACER,
)
from .utils import (
    ACCOUNTS,
    ADDRS,
    MockERC20_ARTIFACT,
    build_and_deploy_contract_async,
    create_contract_transaction,
    derive_new_account,
    send_transaction_async,
    w3_wait_for_new_blocks_async,
)

pytestmark = pytest.mark.asyncio

METHOD = "debug_traceTransaction"
CALL_TRACER = {"tracer": "callTracer"}
TOP_CALL_TRACER = CALL_TRACER | {"tracerConfig": {"onlyTopCall": True}}
COMMUNITY = ACCOUNTS["community"]
RETURN_42_RUNTIME = bytes.fromhex("602a60005260206000f3")
DESTRUCT_RUNTIME = bytes.fromhex("6000ff")  # PUSH1 0 SELFDESTRUCT


@pytest.fixture
def w3(mantra):
    return mantra.async_w3


async def _trace_async(w3, receipt, *config) -> dict:
    """The trace of ``receipt``'s tx; fails on an RPC error."""
    tx_hash = receipt["transactionHash"].to_0x_hex()
    resp = await w3.provider.make_request(METHOD, [tx_hash, *config])
    assert "result" in resp, resp
    return resp["result"]


def _frames(trace: dict) -> list[dict]:
    """A callTracer trace's frames, root first."""
    return [trace, *(f for call in trace.get("calls", []) for f in _frames(call))]


class TestExpected:
    """Traces that match recorded ones."""

    async def test_a_transfer(self, w3):
        to = ADDRS["signer1"]
        tx = {"to": to, "value": 100, "gasPrice": 88500000000}
        receipt = await send_transaction_async(w3, COMMUNITY, **tx)
        assert await _trace_async(w3, receipt) == EXPECTED_STRUCT_TRACER
        assert await _trace_async(w3, receipt, CALL_TRACER) == EXPECTED_CALLTRACERS
        top_call = await _trace_async(w3, receipt, TOP_CALL_TRACER)
        assert top_call == EXPECTED_CALLTRACERS

    async def test_a_creation(self, w3):
        acc = derive_new_account(7)  # the recorded trace's sender
        await send_transaction_async(w3, COMMUNITY, to=acc.address, value=10**18)
        tx = await create_contract_transaction(w3, "TestERC20A", key=acc.key)
        receipt = await send_transaction_async(w3, acc, **tx)
        await w3_wait_for_new_blocks_async(w3, 1)
        trace = await _trace_async(w3, receipt, CALL_TRACER)
        assert trace == EXPECTED_CONTRACT_CREATE_TRACER


class TestMessageCall:
    """Calls into TestMessageCall."""

    @pytest.fixture
    async def contract(self, w3):
        return await build_and_deploy_contract_async(w3, "TestMessageCall")

    async def test_a_call_out_of_gas(self, w3, contract):
        tx = {"from": COMMUNITY.address, "gas": 21510}
        tx = await contract.functions.test(1).build_transaction(tx)
        receipt = await send_transaction_async(w3, COMMUNITY, check=False, **tx)
        trace = await _trace_async(w3, receipt, CALL_TRACER)
        assert "out of gas" in trace["error"], trace

    async def test_a_creation_out_of_gas(self, w3):
        tx = await create_contract_transaction(w3, "TestMessageCall")
        tx["gas"] = 210000
        receipt = await send_transaction_async(w3, COMMUNITY, check=False, **tx)
        trace = await _trace_async(w3, receipt, CALL_TRACER)
        assert "contract creation code storage out of gas" in trace["error"], trace

    async def test_every_tracer_at_once(self, w3, contract):
        tx = {"from": COMMUNITY.address}
        tx = await contract.functions.test(1).build_transaction(tx)
        receipt = await send_transaction_async(w3, COMMUNITY, **tx)
        configs = [
            [],
            [CALL_TRACER],
            [TOP_CALL_TRACER],
            [CALL_TRACER | {"tracerConfig": {"withLog": True}}],
            [CALL_TRACER | {"tracerConfig": {"diffMode": True}}],
        ]
        await asyncio.gather(*(_trace_async(w3, receipt, *c) for c in configs))


async def _deploy(w3, runtime: bytes) -> str:
    """Address of a contract running ``runtime`` (under 256 bytes), deployed once."""
    size = bytes([len(runtime)])
    # Copy the runtime out past these 12 bytes and return it.
    initcode = b"\x60" + size + b"\x60\x0c\x60\x00\x39\x60" + size + b"\x60\x00\xf3"
    return await ensure_deployed_by_create2(w3, COMMUNITY, initcode + runtime)


class TestBatch:
    """Every call of a Multicall3 batch shows in each tracer."""

    @pytest.fixture(autouse=True)
    async def factories(self, w3):
        """The CREATE2 factory and Multicall3."""
        await ensure_create2_deployed(w3, COMMUNITY)
        await ensure_multicall3_deployed(w3, COMMUNITY)

    async def test_call_tracer(self, w3):
        """Each call is a frame, the CREATE2 one included."""
        initcode = get_initcode(MockERC20_ARTIFACT, "TEST", "TEST", 18)
        salt = os.urandom(32)  # a fresh address each run, or the CREATE2 call reverts
        token = create2_address(initcode, salt)
        calls = [
            Call3(CREATE2_FACTORY, data=salt + initcode),
            Call3(token, data=ERC20.fns.balanceOf(COMMUNITY.address).data),
        ]
        receipt = await MULTICALL3.fns.aggregate3(calls).transact(w3, COMMUNITY)
        trace = await _trace_async(w3, receipt, CALL_TRACER)
        frames = [(f["type"], f["to"].lower()) for f in _frames(trace)]
        assert ("CREATE2", token.lower()) in frames, frames
        assert ("CALL", token.lower()) in frames, frames

    async def test_only_top_call_keeps_the_batch(self, w3):
        """The batch is one call into Multicall3: `onlyTopCall` keeps it alone."""
        target = await _deploy(w3, RETURN_42_RUNTIME)
        batch = MULTICALL3.fns.aggregate3([Call3(target)] * 2)
        receipt = await batch.transact(w3, COMMUNITY)
        trace = await _trace_async(w3, receipt, TOP_CALL_TRACER)
        assert (
            trace["to"].lower() == MULTICALL3_ADDRESS.lower() and "calls" not in trace
        )
        assert len((await _trace_async(w3, receipt, CALL_TRACER))["calls"]) == 2

    async def test_struct_logs(self, w3):
        """A call logs the opcodes it logs when sent alone, one level deeper."""
        target = await _deploy(w3, RETURN_42_RUNTIME)
        batch = MULTICALL3.fns.aggregate3([Call3(target)] * 2)
        receipts = [
            await send_transaction_async(w3, COMMUNITY, to=target),
            await batch.transact(w3, COMMUNITY),
        ]
        alone, batch = [(await _trace_async(w3, r))["structLogs"] for r in receipts]
        call = [(log["op"], log["depth"] + 1) for log in alone]
        assert call, "a single call's struct logs"
        nested = [(log["op"], log["depth"]) for log in batch if log["depth"] > 1]
        assert nested == call * 2

    async def test_the_root_reports_its_tx(self, w3):
        """Alone or in a batch, the root carries the tx's sender, gas and outcome."""
        target = await _deploy(w3, RETURN_42_RUNTIME)
        batch = MULTICALL3.fns.aggregate3([Call3(target)] * 2)
        receipts = [
            await send_transaction_async(w3, COMMUNITY, to=target),
            await batch.transact(w3, COMMUNITY),
        ]
        for receipt in receipts:
            gas_used = receipt["gasUsed"]
            root = await _trace_async(w3, receipt, CALL_TRACER)
            assert root["from"].lower() == COMMUNITY.address.lower()
            assert int(root["gasUsed"], 16) == gas_used and "error" not in root
            default = await _trace_async(w3, receipt)
            assert default["gas"] == gas_used and not default["failed"]

    async def test_a_self_destruct_is_traced_once(self, w3):
        """A batch whose last call self-destructs shows that self-destruct alone."""
        ok = await _deploy(w3, RETURN_42_RUNTIME)
        doomed = await _deploy(w3, DESTRUCT_RUNTIME)
        calls = [Call3(ok), Call3(doomed)]
        receipt = await MULTICALL3.fns.aggregate3(calls).transact(w3, COMMUNITY)
        trace = await _trace_async(w3, receipt, CALL_TRACER)
        frames = _frames(trace)
        destroyed = [f["from"].lower() for f in frames if f["type"] == "SELFDESTRUCT"]
        assert destroyed == [doomed.lower()], trace

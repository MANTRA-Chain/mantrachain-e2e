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
    derive_random_account,
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
PRICE = 88500000000
GAS = 100000  # a fixed limit: the chains estimate different ones
FUND = 3 * 10**18
# TODO: remove each skip once mantra traces as geth does there.
OOG_GAS_USED_IS_ZERO = pytest.mark.skip(
    reason="mantra's callTracer reports gasUsed 0 for an out-of-gas tx, geth its gas"
)
NESTED_LOGS_MISSING = pytest.mark.skip(
    reason="mantra's callTracer withLog leaves out a nested call's logs"
)
PRESTATE_TRACER = {"tracer": "prestateTracer"}
PRESTATE_DIFF = PRESTATE_TRACER | {"tracerConfig": {"diffMode": True}}
GAS_CAP = 30000000  # json-rpc gas-cap in configs/default.jsonnet
REVERT_WITH_MSG = "0x9ffb86a5"  # TestRevert.revertWithMsg()
TRACE_CALL_IS_FREE = pytest.mark.skip(
    reason="mantra's debug_traceCall checks no balance, charges no fee, bumps no nonce"
)
NO_STATE_OVERRIDES = pytest.mark.skip(
    reason="mantra's debug_traceCall ignores stateOverrides"
)
NO_BLOCK_OVERRIDES = pytest.mark.skip(
    reason="mantra's debug_traceCall ignores blockOverrides"
)


@pytest.fixture
def w3(mantra):
    return mantra.async_w3


@pytest.fixture
def sender():
    """A fresh account: what it deploys has one address on mantra and on geth."""
    return derive_random_account()


@pytest.fixture
def on_both(mantra, geth, sender):
    """Runs ``run(w3)`` on mantra and on geth, each with ``sender`` funded, and
    returns the result, which the two must share."""

    async def on_both(run):
        async def funded(w3):
            await _fund(w3, sender)
            return await run(w3)

        on_mantra, on_geth = await asyncio.gather(
            funded(mantra.async_w3), funded(geth.async_w3)
        )
        assert on_mantra == on_geth
        return on_mantra

    return on_both


async def _fund(w3, acc, value=FUND):
    await send_transaction_async(w3, COMMUNITY, to=acc.address, value=value)


async def _trace_async(w3, receipt, config=None) -> dict:
    """The trace of ``receipt``'s tx; fails on an RPC error."""
    params = [receipt["transactionHash"].to_0x_hex(), config or {}]
    resp = await w3.provider.make_request(METHOD, params)
    assert "result" in resp, resp
    return resp["result"]


async def _trace_call_async(w3, tx, config=None, block="latest") -> dict:
    """The trace of ``tx`` called on ``block``; fails on an RPC error."""
    params = [tx, block, config or {}]
    resp = await w3.provider.make_request("debug_traceCall", params)
    assert "result" in resp, resp
    return resp["result"]


def _frames(trace: dict) -> list[dict]:
    """A callTracer trace's frames, root first."""
    return [trace, *(f for call in trace.get("calls", []) for f in _frames(call))]


class TestExpected:
    """Traces that match recorded ones, and geth's."""

    async def test_a_transfer(self, on_both):
        async def trace(w3):
            tx = {"to": ADDRS["signer1"], "value": 100, "gasPrice": PRICE}
            receipt = await send_transaction_async(w3, COMMUNITY, **tx)
            configs = [None, CALL_TRACER, TOP_CALL_TRACER]
            return [await _trace_async(w3, receipt, c) for c in configs]

        traces = await on_both(trace)
        assert traces == [EXPECTED_STRUCT_TRACER, *[EXPECTED_CALLTRACERS] * 2]

    async def test_a_creation(self, on_both):
        acc = derive_new_account(7)  # the recorded trace's sender

        async def trace(w3):
            await _fund(w3, acc, 10**18)
            tx = await create_contract_transaction(w3, "TestERC20A", key=acc.key)
            # The recorded limit, for the chains estimate different ones.
            tx["gas"] = int(EXPECTED_CONTRACT_CREATE_TRACER["gas"], 16)
            receipt = await send_transaction_async(w3, acc, **tx)
            await w3_wait_for_new_blocks_async(w3, 1)
            return await _trace_async(w3, receipt, CALL_TRACER)

        assert await on_both(trace) == EXPECTED_CONTRACT_CREATE_TRACER


class TestMessageCall:
    """TestMessageCall.test(1), deployed and called by ``sender``."""

    @pytest.fixture
    def traces(self, on_both, sender):
        """The call's traces under each of ``configs``."""

        async def traces(configs, gas=GAS, check=True):
            async def run(w3):
                contract = await build_and_deploy_contract_async(
                    w3, "TestMessageCall", key=sender.key
                )
                tx = {"from": sender.address, "gas": gas}
                tx = await contract.functions.test(1).build_transaction(tx)
                receipt = await send_transaction_async(w3, sender, check=check, **tx)
                return [await _trace_async(w3, receipt, c) for c in configs]

            return await on_both(run)

        return traces

    @OOG_GAS_USED_IS_ZERO
    async def test_a_call_out_of_gas(self, traces):
        (trace,) = await traces([CALL_TRACER], gas=21510, check=False)
        assert "out of gas" in trace["error"], trace

    @OOG_GAS_USED_IS_ZERO
    async def test_a_creation_out_of_gas(self, on_both, sender):
        async def trace(w3):
            tx = await create_contract_transaction(
                w3, "TestMessageCall", key=sender.key
            )
            tx["gas"] = 210000
            receipt = await send_transaction_async(w3, sender, check=False, **tx)
            return await _trace_async(w3, receipt, CALL_TRACER)

        trace = await on_both(trace)
        assert "contract creation code storage out of gas" in trace["error"], trace

    async def test_every_tracer(self, traces):
        diff_mode = CALL_TRACER | {"tracerConfig": {"diffMode": True}}
        await traces([None, CALL_TRACER, TOP_CALL_TRACER, diff_mode])

    @NESTED_LOGS_MISSING
    async def test_with_log(self, traces):
        await traces([CALL_TRACER | {"tracerConfig": {"withLog": True}}])


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


class TestStaticCall:
    """Caller's STATICCALL into Calculator."""

    async def test_it_traces_as_on_geth(self, on_both, sender):
        """With or without an access list for Calculator's slots."""
        other = derive_random_account()
        slots = [f"0x{i:064x}" for i in range(2)]

        async def trace(w3):
            await _fund(w3, other)
            calc = await build_and_deploy_contract_async(
                w3, "Caller", key=sender.key, contract="Calculator"
            )
            caller = await build_and_deploy_contract_async(
                w3, "Caller", (calc.address,), key=sender.key
            )
            data = caller.encode_abi("callCalculator")
            tx = {"to": caller.address, "data": data, "gas": GAS}
            access_list = [{"address": calc.address, "storageKeys": slots}]
            receipts = await asyncio.gather(
                send_transaction_async(w3, sender, **tx),
                send_transaction_async(w3, other, **tx, accessList=access_list),
            )
            return [await _trace_async(w3, r, CALL_TRACER) for r in receipts]

        traces = await on_both(trace)
        assert [[c["type"] for c in t["calls"]] for t in traces] == [["STATICCALL"]] * 2


class TestSelfDestruct:
    """Txs of one sender that self-destruct, sent together."""

    async def test_each_is_traced_after_the_ones_before(self, w3, sender):
        """A sender left just enough for three still traces the third."""
        await _fund(w3, sender, 10**18)
        contract = await build_and_deploy_contract_async(
            w3, "Selfdestruct", key=sender.key
        )
        exploit = contract.functions.exploit()
        tx = {"from": sender.address, "value": 353434350000000000}
        tx |= {"gas": 2 * await exploit.estimate_gas(tx), "gasPrice": 5050000000000}
        cost = tx["gas"] * tx["gasPrice"] + tx["value"]
        balance = await w3.eth.get_balance(sender.address)
        await _fund(w3, sender, 3 * cost - balance)
        nonce = await w3.eth.get_transaction_count(sender.address)
        raws = [
            sender.sign_transaction(
                await exploit.build_transaction(tx | {"nonce": nonce + i})
            ).raw_transaction
            for i in range(3)
        ]
        for tx_hash in [await w3.eth.send_raw_transaction(raw) for raw in raws]:
            receipt = await w3.eth.wait_for_transaction_receipt(tx_hash)
            assert receipt["status"] == 1, receipt
            trace = await _trace_async(w3, receipt, CALL_TRACER)
            types = [f["type"] for f in _frames(trace)]
            assert "error" not in trace and "SELFDESTRUCT" in types, trace


class TestTraceCall:
    """debug_traceCall, as on geth unless mantra's own defaults are at stake."""

    @TRACE_CALL_IS_FREE
    async def test_a_sender_without_funds(self, on_both, sender):
        """Can't pay for the call; a funded sender traces it."""
        tx = {"to": ADDRS["signer1"], "value": hex(100), "gas": hex(21000)}

        async def trace(w3):
            poor = tx | {"from": "0x1000000000000000000000000000000000000000"}
            poor["gasPrice"] = hex(await w3.eth.gas_price)
            for tracer in (PRESTATE_TRACER, CALL_TRACER):
                params = [poor, "latest", tracer]
                resp = await w3.provider.make_request("debug_traceCall", params)
                assert "insufficient" in str(resp.get("error")), resp
            call = tx | {"from": sender.address}
            configs = [None, CALL_TRACER, TOP_CALL_TRACER]
            return [await _trace_call_async(w3, call, c) for c in configs]

        call = EXPECTED_CALLTRACERS | {"from": sender.address.lower()}
        assert await on_both(trace) == [EXPECTED_STRUCT_TRACER, call, call]

    async def test_struct_logs(self, w3, on_both, sender):
        """A transfer runs no opcode; without a gas limit it still uses 21000."""
        to = derive_random_account().address  # not signer2, which test_7702 delegates
        tx = {"from": sender.address, "to": to, "value": hex(100)}

        def trace(w3):
            return _trace_call_async(w3, tx | {"gas": hex(21000)})

        assert await on_both(trace) == EXPECTED_STRUCT_TRACER
        assert await _trace_call_async(w3, tx) == EXPECTED_STRUCT_TRACER

    async def test_call_tracer(self, w3, on_both, sender):
        """Without a gas limit, mantra gives the call its gas cap."""
        to = derive_random_account().address
        tx = {"from": sender.address, "to": to, "value": hex(1)}

        def trace(w3):
            return _trace_call_async(w3, tx | {"gas": hex(21000)}, CALL_TRACER)

        expected = {
            "type": "CALL",
            "from": sender.address.lower(),
            "to": to.lower(),
            "value": hex(1),
            "gas": hex(21000),
            "gasUsed": hex(21000),
            "input": "0x",
        }
        assert await on_both(trace) == expected
        trace = await _trace_call_async(w3, tx, CALL_TRACER)
        assert trace == expected | {"gas": hex(GAS_CAP)}

    async def test_prestate_tracer(self, on_both, sender):
        """Shows the balance and nonce of each party."""
        receiver = derive_random_account()

        async def trace(w3):
            await _fund(w3, receiver)
            for a, b in ((sender, receiver), (receiver, sender)):  # nonces above 0
                tx = {"to": b.address, "value": 1, "gas": 21000, "gasPrice": PRICE}
                await send_transaction_async(w3, a, **tx)
            tx = {"from": sender.address, "to": receiver.address, "value": hex(1)}
            result = await _trace_call_async(w3, tx, PRESTATE_TRACER)
            states = {}
            for addr in (sender.address, receiver.address):
                states[addr.lower()] = {
                    "balance": hex(await w3.eth.get_balance(addr)),
                    "nonce": await w3.eth.get_transaction_count(addr),
                }
            assert states.items() <= result.items(), result
            return states

        await on_both(trace)

    @TRACE_CALL_IS_FREE
    async def test_prestate_diff(self, on_both, sender):
        """Shows what the call changes on the block it is called on."""
        receiver = derive_random_account().address

        async def trace(w3):
            tx = {"to": receiver, "value": 1, "gas": 21000, "gasPrice": PRICE}
            receipts = [
                await send_transaction_async(w3, sender, **tx) for _ in range(3)
            ]
            call = {"from": sender.address, "to": receiver, "value": hex(1)}
            block = hex(receipts[1]["blockNumber"])  # after two of the three
            return await _trace_call_async(w3, call, PRESTATE_DIFF, block)

        payer, payee = sender.address.lower(), receiver.lower()
        balance = FUND - 2 * 21000 * PRICE
        assert await on_both(trace) == {
            "pre": {
                payee: {"balance": hex(2)},
                payer: {"balance": hex(balance - 2), "nonce": 2},
            },
            "post": {
                payee: {"balance": hex(3)},
                payer: {"balance": hex(balance - 3), "nonce": 3},
            },
        }

    @NO_STATE_OVERRIDES
    async def test_state_overrides(self, on_both):
        """The call's sender takes the balance and nonce it is given."""
        poor = derive_random_account().address
        state = {"balance": hex(10**22), "nonce": 1000}
        overrides = {poor: state | {"nonce": hex(state["nonce"])}}
        tx = {"from": poor, "to": derive_random_account().address, "value": hex(1)}
        tx |= {"gas": hex(21000), "gasPrice": hex(PRICE)}

        async def trace(w3):
            config = PRESTATE_TRACER | {"stateOverrides": overrides}
            return (await _trace_call_async(w3, tx, config))[poor.lower()]

        assert await on_both(trace) == state

    async def test_revert_data(self, on_both):
        async def trace(w3):
            test_revert = await build_and_deploy_contract_async(w3, "TestRevert")
            tx = {"from": ADDRS["validator"], "to": test_revert.address}
            tx["data"] = REVERT_WITH_MSG
            return (await _trace_call_async(w3, tx))["returnValue"]

        value = await on_both(trace)
        assert b"Function has been reverted".hex() in value, value

    @NO_BLOCK_OVERRIDES
    async def test_block_overrides(self, on_both):
        """NUMBER reads the block number the call is given."""
        tx = {"from": ADDRS["validator"], "input": "0x43"}  # NUMBER, in initcode
        tx |= {"gas": hex(65535), "gasPrice": hex(PRICE)}
        block = {
            "number": "0x1337",
            "coinbase": "0x1111111111111111111111111111111111111111",
            "difficulty": hex(2),
            "baseFee": hex(5),
        }

        async def trace(w3):
            await w3_wait_for_new_blocks_async(w3, 1)
            return await _trace_call_async(w3, tx, {"blockOverrides": block})

        logs = (await on_both(trace))["structLogs"]
        steps = [(log["op"], log["stack"]) for log in logs]
        assert steps == [("NUMBER", []), ("STOP", ["0x1337"])], logs

    @TRACE_CALL_IS_FREE
    async def test_a_revert_refunds_unused_gas(self, w3, sender):
        """A reverted call is charged the gas it used, traced as on chain."""
        await _fund(w3, sender)
        test_revert = await build_and_deploy_contract_async(w3, "TestRevert")
        tx = {"to": test_revert.address, "data": REVERT_WITH_MSG}
        gas, price = 1000000, 6060000000000
        call = tx | {"from": sender.address, "gas": hex(gas), "gasPrice": hex(price)}
        diff = await _trace_call_async(w3, call, PRESTATE_DIFF)
        payer = sender.address.lower()
        assert payer in diff["pre"], diff
        traced = int(diff["pre"][payer]["balance"], 16)
        traced -= int(diff["post"][payer]["balance"], 16)
        before = await w3.eth.get_balance(sender.address)
        tx |= {"gas": gas, "gasPrice": price}
        receipt = await send_transaction_async(w3, sender, check=False, **tx)
        assert receipt["status"] == 0, receipt
        paid = before - await w3.eth.get_balance(sender.address)
        assert traced == paid == receipt["gasUsed"] * price < gas * price

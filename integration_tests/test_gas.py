import pytest
import requests
import web3

from .utils import (
    ACCOUNTS,
    ADDRS,
    DEFAULT_DENOM,
    DEFAULT_GAS_PRICE,
    build_and_deploy_contract_async,
)
from .utils import send_transaction_async as send_transaction
from .utils import (
    w3_wait_for_new_blocks_async,
)

pytestmark = pytest.mark.asyncio

PRECOMPILE_P256 = "0x0000000000000000000000000000000000000100"


def eip7623_floor(data: bytes) -> int:
    """21000 + 10 gas per calldata token: 1 per zero byte, 4 per non-zero byte."""
    zeros = data.count(0)
    return 21000 + 10 * (zeros + 4 * (len(data) - zeros))


# drop once mantrachaind picks up evm#1186
evmd_only = pytest.mark.skipif(
    "config.getoption('chain_config') != 'evmd'",
    reason="evm#1186 is not in mantrachaind yet",
)


BURN_GAS_CONTRACT = None


async def get_burn_gas_contract(w3):
    global BURN_GAS_CONTRACT
    if BURN_GAS_CONTRACT is None:
        BURN_GAS_CONTRACT = await build_and_deploy_contract_async(w3, "BurnGas")
    return BURN_GAS_CONTRACT


async def test_gas_call(mantra):
    w3 = mantra.async_w3
    input = 10
    contract = await get_burn_gas_contract(w3)
    txhash = await contract.functions.burnGas(input).transact(
        {"from": ADDRS["community"], "gasPrice": await w3.eth.gas_price}
    )
    receipt = await w3.eth.wait_for_transaction_receipt(txhash)
    assert receipt.gasUsed == 267441


class TestEIP7623:
    """gasUsed never drops below the calldata floor, whatever the tx executes."""

    # non-zero bytes: the floor (40 gas each) exceeds intrinsic (16 gas each)
    DATA = b"\x01" * 2048
    FLOOR = eip7623_floor(DATA)  # 102_920
    # under 2x the floor so min_gas_multiplier (0 here, 0.5 upstream) cannot mask it
    GAS = 40_000

    async def _send(self, w3, to, data, gas):
        return await send_transaction(
            w3, ACCOUNTS["community"], to=to, data=data, gas=gas
        )

    async def test_floor_is_charged(self, mantra):
        """plain EOA call: 53768 intrinsic, charged the 102920 floor"""
        receipt = await self._send(
            mantra.async_w3, ADDRS["signer1"], self.DATA, 200_000
        )
        assert receipt.gasUsed == self.FLOOR, receipt.gasUsed

    async def test_below_floor_is_rejected(self, mantra):
        with pytest.raises(web3.exceptions.Web3RPCError, match="floor data gas"):
            await self._send(
                mantra.async_w3, ADDRS["signer1"], self.DATA, self.FLOOR - 1
            )

    @evmd_only
    async def test_floor_binds_after_refund(self, mantra):
        """23048 intrinsic + ~5000 SSTORE > 26120 floor until the 4800 clear refund"""
        w3 = mantra.async_w3
        contract = await build_and_deploy_contract_async(w3, "StorageClear")
        data = b"\x01" * 128
        receipt = await self._send(w3, contract.address, data, self.GAS)
        assert receipt.gasUsed == eip7623_floor(data), receipt.gasUsed

    @evmd_only
    async def test_floor_binds_on_precompile_call(self, mantra):
        """23560 intrinsic + 3450 P-256 verify < 27400 floor, with no refund"""
        data = b"\x01" * 160
        receipt = await self._send(mantra.async_w3, PRECOMPILE_P256, data, self.GAS)
        assert receipt.gasUsed == eip7623_floor(data), receipt.gasUsed


async def test_block_gas_limit(mantra):
    w3 = mantra.async_w3
    # get the block gas limit from the latest block
    await w3_wait_for_new_blocks_async(w3, 5)
    block = await w3.eth.get_block("latest")
    exceeded_gas_limit = block.gasLimit + 100

    # send a transaction exceeding the block gas limit
    gas_price = await w3.eth.gas_price
    value = 10
    tx = {
        "to": ADDRS["signer1"],
        "value": value,
        "gas": exceeded_gas_limit,
        "gasPrice": gas_price,
    }
    # expect an error due to the block gas limit
    msg = "exceeds block gas limit"
    sender = ADDRS["community"]
    with pytest.raises(web3.exceptions.Web3RPCError, match=msg):
        await send_transaction(w3, sender, False, **tx)

    # expect an error on contract call due to block gas limit
    with pytest.raises(web3.exceptions.Web3RPCError, match=msg):
        contract = await get_burn_gas_contract(w3)
        await contract.functions.burnGas(exceeded_gas_limit).transact(
            {
                "from": sender,
                "gas": exceeded_gas_limit,
                "gasPrice": gas_price,
            }
        )


async def test_cosmos_tx_block_gas_limit(mantra):
    """Cosmos tx above the block gas limit is rejected at CheckTx."""
    cli = mantra.cosmos_cli(0)
    rsp = requests.get(f"{cli.node_rpc_http}/consensus_params").json()
    max_gas = int(rsp["result"]["consensus_params"]["block"]["max_gas"])
    assert max_gas > 0, "the check only binds on a finite block gas limit"

    community = cli.address("community")
    receiver = cli.address("signer1")

    def transfer(gas, **kwargs):
        return cli.transfer(
            community,
            receiver,
            f"1{DEFAULT_DENOM}",
            gas=gas,
            gas_prices=DEFAULT_GAS_PRICE,
            **kwargs,
        )

    # sdk v0.54 disables the block gas meter, leaving SetUpContextDecorator
    rsp = transfer(max_gas + 1, event_query_tx=False)
    assert rsp["code"] != 0, rsp
    assert "exceeds block max gas" in rsp["raw_log"], rsp["raw_log"]

    # a normally sized transfer still goes through
    rsp = transfer(200000)
    assert rsp["code"] == 0, rsp["raw_log"]

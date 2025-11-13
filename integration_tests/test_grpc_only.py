import base64
import subprocess
from pathlib import Path

import pytest
from eth_contract.utils import send_transaction as send_transaction_async
from pystarport import ports
from pystarport.utils import wait_for_block, wait_for_port

from .network import setup_custom_mantra
from .utils import (
    ADDRS,
    CHAIN_ID,
    CMD,
    EVM_CHAIN_ID,
    AsyncContract,
    decode_bech32,
    grpc_eth_call,
    supervisorctl,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def custom_mantra(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp("grpc-only")
    yield from setup_custom_mantra(
        path,
        26920,
        Path(__file__).parent / "configs/fullnode.jsonnet",
        chain=chain,
    )


async def test_grpc_mode(custom_mantra):
    w3 = custom_mantra.async_w3
    async_contract = AsyncContract("ChainID")
    acct = async_contract.acct
    await async_contract.deploy(w3)
    to = async_contract.address
    contract = async_contract.contract
    data = contract.fns.currentChainID().data.hex()
    msg = {"to": to, "data": f"0x{data}"}
    base_port = custom_mantra.base_port(1)
    api_port = ports.api_port(base_port)
    grpc_port = ports.grpc_port(base_port)
    evmrpc_port = ports.evmrpc_port(base_port)

    def expect_cb_normal(rsp):
        ret = rsp.get("ret")
        if ret is None:
            return False
        return EVM_CHAIN_ID == int.from_bytes(base64.b64decode(ret.encode()), "big")

    grpc_eth_call(api_port, msg, expect_cb_normal)

    # in normal mode, grpc query works even if we don't pass chain_id explicitly
    grpc_eth_call(api_port, msg, expect_cb_normal)

    # wait 1 more block for both nodes to avoid node stopped before tnx get included
    for i in range(2):
        wait_for_block(custom_mantra.cosmos_cli(i), 1)

    base_dir = custom_mantra.base_dir
    supervisorctl(base_dir / "../tasks.ini", "stop", f"{CHAIN_ID}-node1")

    # run grpc-only mode directly with existing chain state
    with (base_dir / "node1.log").open("a") as logfile:
        cli0 = custom_mantra.cosmos_cli(0)
        proc = subprocess.Popen(
            [
                CMD,
                "start",
                "--grpc-only",
                "--json-rpc.enable",
                "--home",
                base_dir / "node1",
                "--node",
                cli0.node_rpc,
            ],
            stdout=logfile,
            stderr=subprocess.STDOUT,
        )
        try:
            for port in (grpc_port, api_port, evmrpc_port):
                wait_for_port(port)

            # pass the first validator's consensus address to grpc query
            grpc_eth_call(
                api_port, msg, lambda rsp: "code" not in rsp, chain_id=EVM_CHAIN_ID
            )

            # Get consensus address and prepare more strict expect_cb
            cons_addr = decode_bech32(cli0.consensus_address())

            def expect_cb_strict(rsp):
                if "code" in rsp:
                    return False
                ret = base64.b64decode(rsp["ret"].encode())
                return EVM_CHAIN_ID == int.from_bytes(ret, "big")

            # should work with both chain_id and proposer_address set
            grpc_eth_call(
                api_port,
                msg,
                expect_cb_strict,
                chain_id=100,
                proposer_address=base64.b64encode(cons_addr).decode(),
            )
            w3 = custom_mantra.async_node_w3(i=1)
            assert await w3.eth.gas_price > 0
            # test read-only contract call works
            chain_id_result = await contract.fns.currentChainID().call(w3, to=to)
            assert chain_id_result == EVM_CHAIN_ID
            tx = {
                "from": acct.address,
                "to": ADDRS["signer1"],
                "value": 1000,
                "gas": 21000,
            }
            await send_transaction_async(w3, acct, **tx)
        finally:
            proc.terminate()
            proc.wait()

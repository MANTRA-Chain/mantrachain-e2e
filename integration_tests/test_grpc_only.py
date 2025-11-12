import base64
import subprocess
from pathlib import Path

import pytest
from pystarport import ports
from pystarport.utils import wait_for_block, wait_for_port
from web3._utils.contracts import encode_transaction_data

from .network import setup_custom_mantra
from .utils import (
    CHAIN_ID,
    CMD,
    EVM_CHAIN_ID,
    Contract,
    decode_bech32,
    grpc_eth_call,
    supervisorctl,
)

pytest.skip("wait next bump deps", allow_module_level=True)


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


def test_grpc_mode(custom_mantra):
    w3 = custom_mantra.w3
    contract = Contract("ChainID")
    data = encode_transaction_data(
        w3, "currentChainID", contract.abi, args=[], kwargs={}
    )
    contract.deploy(w3)
    contract = contract.contract

    msg = {
        "to": contract.address,
        "data": data,
    }
    api_port = ports.api_port(custom_mantra.base_port(1))

    def expect_cb(rsp):
        ret = rsp.get("ret")
        valid = ret is not None
        return valid and EVM_CHAIN_ID == int.from_bytes(
            base64.b64decode(ret.encode()), "big"
        )

    # in normal mode, grpc query works even if we don't pass chain_id explicitly
    grpc_eth_call(api_port, msg, expect_cb)
    # wait 1 more block for both nodes to avoid node stopped before tnx get included
    base_dir = custom_mantra.base_dir
    for i in range(2):
        wait_for_block(custom_mantra.cosmos_cli(i), 1)
    supervisorctl(base_dir / "../tasks.ini", "stop", f"{CHAIN_ID}-node1")

    # run grpc-only mode directly with existing chain state
    with (base_dir / "node1.log").open("a") as logfile:
        proc = subprocess.Popen(
            [
                CMD,
                "start",
                "--grpc-only",
                "--home",
                base_dir / "node1",
            ],
            stdout=logfile,
            stderr=subprocess.STDOUT,
        )
        try:
            # wait for grpc and rest api ports
            grpc_port = ports.grpc_port(custom_mantra.base_port(1))
            wait_for_port(grpc_port)
            wait_for_port(api_port)

            def expect_cb(rsp):
                return "code" not in rsp

            # it defaults to empty address without proposer address
            grpc_eth_call(api_port, msg, expect_cb, chain_id=EVM_CHAIN_ID)

            # pass the first validator's consensus address to grpc query
            addr = custom_mantra.cosmos_cli(0).consensus_address()
            cons_addr = decode_bech32(addr)

            def expect_cb(rsp):
                ret = base64.b64decode(rsp["ret"].encode())
                return "code" not in rsp and EVM_CHAIN_ID == int.from_bytes(ret, "big")

            # should work with both chain_id and proposer_address set
            grpc_eth_call(
                api_port,
                msg,
                expect_cb,
                chain_id=100,
                proposer_address=base64.b64encode(cons_addr).decode(),
            )
        finally:
            proc.terminate()
            proc.wait()

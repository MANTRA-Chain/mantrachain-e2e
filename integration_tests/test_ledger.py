import socket
import time
from pathlib import Path

import grpc
import pytest
from pystarport.ledger import ZEMU_GRPC_SERVER_PORT, Ledger

from .network import setup_custom_mantra
from .utils import DEFAULT_DENOM, find_fee

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def custom_mantra(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp("hw")
    ledger = Ledger()
    try:
        ledger.start()
        assert (
            ledger.is_running() and wait_for_grpc_server()
        ), "failed to start Ledger simulator"

        yield from setup_custom_mantra(
            path,
            27300,
            Path(__file__).parent / "configs/hw.jsonnet",
            chain=chain,
        )
    finally:
        try:
            ledger.stop()
        except Exception as e:
            print(f"error during ledger cleanup: {e}")


def test_ledger(custom_mantra):
    cli = custom_mantra.cosmos_cli()
    name = "hw"
    hw = cli.address(name)
    community = cli.address("community")
    amt1 = 8000
    assert cli.balance(hw) == amt1
    community_balance = cli.balance(community)
    amt2 = 4000
    rsp = cli.transfer(
        hw, community, f"{amt2}{DEFAULT_DENOM}", ledger=True, sign_mode="amino-json"
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    assert cli.balance(hw) == amt2 - find_fee(rsp)
    assert cli.balance(community) == community_balance + amt2


def wait_for_grpc_server(port=ZEMU_GRPC_SERVER_PORT, timeout=60):
    for i in range(timeout):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    try:
                        channel = grpc.insecure_channel(f"127.0.0.1:{port}")
                        grpc.channel_ready_future(channel).result(timeout=5)
                        channel.close()
                        print(f"gRPC server ready after {i+1}s")
                        return True
                    except Exception as grpc_error:
                        if i % 10 == 0:
                            print(f"gRPC not ready yet ({i+1}s): {grpc_error}")
                elif i % 10 == 0:
                    print(f"wait for gRPC server ({i+1}s)")
        except Exception as e:
            if i % 15 == 0:
                print(f"gRPC connection error ({i+1}s): {e}")
        time.sleep(1)

    print(f"gRPC server not ready after {timeout}s")
    return False

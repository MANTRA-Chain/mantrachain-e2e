import json
import socket
import subprocess
import time

import grpc
from pystarport.ledger import ZEMU_GRPC_SERVER_PORT, Ledger


def test_ledger(tmp_path):
    ledger = Ledger()
    name = "ledger"
    try:
        ledger.start()
        if not ledger.is_running() or not wait_for_grpc_server():
            raise RuntimeError("Ledger simulator or gRPC server failed to start")

        cmd = [
            "mantrachaind",
            "keys",
            "add",
            name,
            "--ledger",
            "--output",
            "json",
            "--keyring-backend",
            "test",
            "--coin-type",
            "118",
            "--key-type",
            "secp256k1",
            "--home",
            str(tmp_path / name),
        ]

        print(f"Running command: {' '.join(cmd)}")
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        stdout, stderr = proc.communicate(timeout=60)
        print(f"Code: {proc.returncode}, STDOUT: {stdout}, STDERR: {stderr}")
        if proc.returncode != 0:
            raise RuntimeError(f"mantrachaind failed: {stderr or 'Unknown error'}")

        acct = json.loads(stdout)
        assert acct["address"]
        assert acct["name"] == name
        assert acct["type"] == "ledger"
        assert "pubkey" in acct

    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError("mantrachaind command timed out")
    except Exception as e:
        print(f"Test failed: {e}")
        try:
            for container_info in ledger.containers:
                container = ledger.client.containers.get(container_info["Id"])
                print(f"\n=== Container {container_info['Name']} logs ===")
                print(container.logs().decode("utf-8"))
        except Exception as log_error:
            print(f"Could not retrieve logs: {log_error}")
        raise
    finally:
        try:
            ledger.stop()
        except Exception as e:
            print(f"Error during cleanup: {e}")


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
                        print(f"gRPC not ready yet ({i+1}s): {grpc_error}")
                elif i % 10 == 0:
                    print(f"still installing grpc ({i+1}s)")
        except Exception as e:
            if i % 15 == 0:
                print(f"Waiting for gRPC ({i+1}s): {e}")
        time.sleep(1)
    print(f"gRPC server not ready after {timeout}s")
    return False

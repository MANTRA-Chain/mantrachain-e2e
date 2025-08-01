import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

from pystarport import cluster, ports

from .network import Hermes, Mantra, setup_custom_mantra
from .utils import (
    DEFAULT_DENOM,
    wait_for_new_blocks,
    wait_for_port,
)


class IBCNetwork(NamedTuple):
    ibc1: Mantra
    ibc2: Mantra
    hermes: Hermes | None


def call_hermes_cmd(hermes, incentivized, version):
    subprocess.check_call(
        [
            "hermes",
            "--config",
            hermes.configpath,
            "create",
            "channel",
            "--a-port",
            "transfer",
            "--b-port",
            "transfer",
            "--a-chain",
            "mantra-canary-net-1",
            "--b-chain",
            "mantra-canary-net-2",
            "--new-client-connection",
            "--yes",
        ]
        + (
            [
                "--channel-version",
                json.dumps(version),
            ]
            if incentivized
            else []
        )
    )


def prepare_network(tmp_path, name):
    name = f"configs/{name}.jsonnet"
    with contextmanager(setup_custom_mantra)(
        tmp_path,
        27000,
        Path(__file__).parent / name,
        relayer=cluster.Relayer.HERMES.value,
    ) as ibc1:
        cli = ibc1.cosmos_cli()
        ibc2 = Mantra(ibc1.base_dir.parent / "mantra-canary-net-2")
        # wait for grpc ready
        wait_for_port(ports.grpc_port(ibc2.base_port(0)))
        wait_for_port(ports.grpc_port(ibc1.base_port(0)))
        wait_for_new_blocks(ibc2.cosmos_cli(), 1)
        wait_for_new_blocks(cli, 1)
        version = {"fee_version": "ics29-1", "app_version": "ics20-1"}
        path = ibc1.base_dir.parent / "relayer"
        hermes = Hermes(path.with_suffix(".toml"))
        call_hermes_cmd(hermes, False, version)
        ibc1.supervisorctl("start", "relayer-demo")
        yield IBCNetwork(ibc1, ibc2, hermes)
        wait_for_port(hermes.port)


def hermes_transfer(ibc, port, channel, src_amount, dst_addr):
    # wait for hermes
    output = subprocess.getoutput(
        f"curl -s -X GET 'http://127.0.0.1:{ibc.hermes.port}/state' | jq"
    )
    assert json.loads(output)["status"] == "success"
    # mantra-canary-net-2 -> mantra-canary-net-1
    ibc2 = "mantra-canary-net-2"
    ibc1 = "mantra-canary-net-1"
    # dstchainid srcchainid srcportid srchannelid
    cmd = (
        f"hermes --config {ibc.hermes.configpath} tx ft-transfer "
        f"--dst-chain {ibc1} --src-chain {ibc2} --src-port {port} "
        f"--src-channel {channel} --amount {src_amount} "
        f"--timeout-height-offset 1000 --number-msgs 1 "
        f"--denom {DEFAULT_DENOM} --receiver {dst_addr} --key-name relayer"
    )
    subprocess.run(cmd, check=True, shell=True)

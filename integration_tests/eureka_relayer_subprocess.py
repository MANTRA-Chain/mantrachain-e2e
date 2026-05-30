"""Subprocess wrapper for the upstream ``ibc-eureka-relayer`` binary.

Spawns the relayer in ``attested`` mode against a pair of EVM endpoints +
:mod:`eureka_attestor_subprocess`-managed attestors. The relayer exposes
its proof API on a gRPC port we hand back to the caller — see
:mod:`eureka_grpc.relayer` for the generated client stubs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from .eureka_subprocess import ManagedProcess, require_binary

_RELAYER_BIN = "relayer"


class _Side(NamedTuple):
    chain_id: str  # EVM chain id, hex with 0x prefix
    rpc_url: str
    ics26_address: str
    attestor_endpoint: str  # gRPC URL of the attestor watching this chain


def build_eth_to_eth_config(
    *,
    grpc_port: int,
    grpc_web_port: int,
    src_chain_id: str,
    src_rpc_url: str,
    src_ics26_address: str,
    src_attestor_endpoint: str,
    dst_chain_id: str,
    dst_rpc_url: str,
    dst_ics26_address: str,
    dst_attestor_endpoint: str,
    quorum_threshold: int = 1,
    log_level: str = "info",
) -> dict:
    """Build a bidirectional ETH↔ETH relayer config in ``attested`` mode.

    ``*_chain_id`` are EVM chain ids (hex ``"0x…"``); each side carries the
    gRPC endpoint of the attestor watching it (used by the module whose
    source is that chain).
    """
    a = _Side(src_chain_id, src_rpc_url, src_ics26_address, src_attestor_endpoint)
    b = _Side(dst_chain_id, dst_rpc_url, dst_ics26_address, dst_attestor_endpoint)

    def _module(from_: _Side, to_: _Side) -> dict:
        return {
            "name": "eth_to_eth",
            "src_chain": from_.chain_id,
            "dst_chain": to_.chain_id,
            "config": {
                "src_chain_id": from_.chain_id,
                "src_rpc_url": from_.rpc_url,
                "src_ics26_address": from_.ics26_address,
                "dst_rpc_url": to_.rpc_url,
                "dst_ics26_address": to_.ics26_address,
                "mode": _attested(from_.attestor_endpoint, quorum_threshold),
            },
        }

    return {
        **_server_observability(grpc_port, grpc_web_port, log_level),
        "modules": [_module(a, b), _module(b, a)],
    }


def _server_observability(grpc_port: int, grpc_web_port: int, log_level: str) -> dict:
    """The ``server`` + ``observability`` top-level blocks shared by every config."""
    return {
        "server": {
            "address": "127.0.0.1",
            "port": grpc_port,
            "grpc_web_port": grpc_web_port,
        },
        "observability": {
            "level": log_level,
            "use_otel": False,
            "service_name": "ibc-eureka-relayer-test",
            "otel_endpoint": None,
        },
    }


def _attested(attestor_endpoint: str, quorum_threshold: int) -> dict:
    """The ``{"attested": AggregatorConfig}`` mode block shared by every module
    (see ``packages/proof-api/lib/src/aggregator/config.rs::Config``).

    ``TxBuilderMode`` is externally-tagged (``enum { Attested(AggregatorConfig) }``),
    so the JSON is ``{"attested": {…}}`` — not the ``{"type": "attested", …}`` form
    the upstream config.example.json shows.
    """
    return {
        "attested": {
            "attestor": {
                "attestor_query_timeout_ms": 5000,
                "quorum_threshold": quorum_threshold,
                "attestor_endpoints": [attestor_endpoint],
            },
            "cache": {
                "state_cache_max_entries": 10000,
                "packet_cache_max_entries": 10000,
            },
        },
    }


def build_eth_to_cosmos_config(
    *,
    grpc_port: int,
    grpc_web_port: int,
    eth_chain_id: str,
    eth_rpc_url: str,
    eth_ics26_address: str,
    eth_attestor_endpoint: str,
    cosmos_chain_id: str,
    cosmos_rpc_url: str,
    cosmos_signer_address: str,
    cosmos_attestor_endpoint: str,
    cosmos_ics26_address: str = "",
    quorum_threshold: int = 1,
    log_level: str = "info",
) -> dict:
    """Bidirectional EVM↔Cosmos relayer config in ``attested`` mode: an
    ``eth_to_cosmos`` recv leg and a ``cosmos_to_eth`` ack leg.

    ``*_chain_id`` are the ids ``BinaryRelayer`` passes to ``RelayByTx`` (EVM
    hex ``"0x…"``, Cosmos the chain-id string). ``cosmos_signer_address`` is the
    bech32 submitter for the *unsigned* ``TxBody`` we sign + broadcast (see
    :func:`eureka_cosmos.sign_and_broadcast_body`).
    """
    eth_to_cosmos = {
        "name": "eth_to_cosmos",
        "src_chain": eth_chain_id,
        "dst_chain": cosmos_chain_id,
        "config": {
            "ics26_address": eth_ics26_address,
            "tm_rpc_url": cosmos_rpc_url,
            "eth_rpc_url": eth_rpc_url,
            "eth_beacon_api_url": "",  # unused in attested mode
            "signer_address": cosmos_signer_address,
            "mode": _attested(eth_attestor_endpoint, quorum_threshold),
        },
    }
    cosmos_to_eth = {
        "name": "cosmos_to_eth",
        "src_chain": cosmos_chain_id,
        "dst_chain": eth_chain_id,
        "config": {
            "tm_rpc_url": cosmos_rpc_url,
            "ics26_address": eth_ics26_address,
            "eth_rpc_url": eth_rpc_url,
            "mode": _attested(cosmos_attestor_endpoint, quorum_threshold),
        },
    }
    return {
        **_server_observability(grpc_port, grpc_web_port, log_level),
        "modules": [eth_to_cosmos, cosmos_to_eth],
    }


@dataclass
class RelayerProcess:
    proc: ManagedProcess
    grpc_address: str  # "host:port"
    config_path: Path

    def stop(self) -> None:
        self.proc.stop()


def start_relayer(
    config: dict, *, work_dir: Path, binary: str = _RELAYER_BIN
) -> RelayerProcess:
    """Write ``config`` and spawn ``<binary> start -c <config>``. Waits for
    the gRPC port to bind. Raises ``FileNotFoundError`` (skip-friendly) if
    the binary isn't on ``$PATH``.
    """
    require_binary(binary)
    work_dir.mkdir(parents=True, exist_ok=True)
    config_path = work_dir / "relayer-config.json"
    config_path.write_text(json.dumps(config, indent=2))

    # CLI is ``relayer start -c <config>`` (Subcommands::Start), not
    # ``relayer -c …`` as the upstream README shows.
    proc = ManagedProcess.spawn(
        [binary, "start", "-c", str(config_path)],
        log_path=work_dir / "relayer.log",
        wait_port=config["server"]["port"],
        name="relayer",
    )
    return RelayerProcess(
        proc=proc,
        grpc_address=f"127.0.0.1:{config['server']['port']}",
        config_path=config_path,
    )

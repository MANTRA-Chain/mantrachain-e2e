from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from eth_utils.address import to_checksum_address

from .eureka_subprocess import ManagedProcess, require_binary
from .utils import free_port

_ATTESTOR_BIN = "ibc_attestor"
_KEYSTORE_NAME = "ibc-attestor-keystore"


@dataclass
class Attestor:
    """Owns one ``ibc_attestor`` instance: keygen on construction, ``start``
    spawns the server once the on-chain target is known, ``stop`` tears down."""

    work_dir: Path
    binary: str = _ATTESTOR_BIN
    address: str = field(init=False)
    # Populated by ``.start()``; "" until then.
    grpc_endpoint: str = field(init=False, default="")
    _proc: ManagedProcess | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        require_binary(self.binary)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._run("key", "generate", "--keystore", str(self.work_dir))
        out = self._run(
            "key", "show", "--show-public", "--keystore", str(self.work_dir), text=True
        )
        self.address = to_checksum_address("0x" + out.stdout.strip())

    def start(
        self,
        *,
        rpc_url: str,
        router_address: str | None = None,
        chain_type: str = "evm",
    ) -> None:
        """Spawn the attestor watching ``rpc_url``.

        ``chain_type="evm"`` needs ``router_address`` (the ICS26Router whose
        commitments are signed); the ``ibc-attestor`` Cosmos adapter
        (``apps/ibc-attestor/src/adapter/cosmos.rs``) takes only ``url``, so
        ``chain_type="cosmos"`` omits ``router_address`` entirely.
        """
        if chain_type == "evm" and router_address is None:
            raise ValueError("router_address is required for chain_type='evm'")
        if self._proc is not None and self._proc.proc.poll() is None:
            raise RuntimeError("attestor already started — stop it first")
        if self._proc is not None and self._proc.proc.poll() is not None:
            self._proc = None
        grpc_port, health_port = free_port(), free_port()
        # finality_offset = 0 → adapter uses `latest` (Cosmos+EVM dev chains
        # don't produce a `finalized` block tag). The cosmos adapter takes no
        # router_address.
        router_line = (
            f'router_address = "{router_address}"\n' if chain_type == "evm" else ""
        )
        config = (
            f'[server]\nlisten_addr = "127.0.0.1:{grpc_port}"\n'
            f'health_addr = "127.0.0.1:{health_port}"\n\n'
            f'[adapter]\nurl = "{rpc_url}"\n{router_line}finality_offset = 0\n\n'
            f'[signer]\nkeystore_path = "{self.work_dir / _KEYSTORE_NAME}"\n'
        )
        config_path = self.work_dir / "attestor-config.toml"
        config_path.write_text(config)

        self._proc = ManagedProcess.spawn(
            [
                self.binary,
                "server",
                "--config",
                str(config_path),
                "--chain-type",
                chain_type,
                "--signer-type",
                "local",
            ],
            log_path=self.work_dir / "attestor.log",
            wait_port=health_port,
            name="attestor",
        )
        self.grpc_endpoint = f"http://127.0.0.1:{grpc_port}"

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.stop()
            self._proc = None
        self.grpc_endpoint = ""

    def _run(self, *args: str, text: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.binary, *args], check=True, capture_output=True, text=text
        )

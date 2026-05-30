"""Python orchestrator for the ``ibc-eureka-relayer`` Rust binary.

The binary is a proof API: given a source tx hash it returns the IBC
``MsgRecvPacket`` / ``MsgAckPacket`` calldata + proofs. This module signs the
returned bytes and submits them on the destination chain. The raw gRPC plumbing
lives in :class:`eureka_grpc.relayer.client.RelayerClient`.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from eth_account.signers.base import BaseAccount
from eth_contract.utils import send_transaction
from eth_typing import ChecksumAddress
from eureka_grpc.relayer.client import RelayerClient
from hexbytes import HexBytes
from web3 import AsyncWeb3


@dataclass
class _Endpoint:
    """One side of a paired Eureka deployment with the signing key."""

    w3: AsyncWeb3
    router_addr: ChecksumAddress
    client_id: str  # local client id
    chain_id: str  # EVM chain id, hex with 0x prefix
    deployer: BaseAccount


class BinaryRelayer:
    """``relay`` calls ``RelayByTx`` from→to and submits the returned
    multicall (``updateClient + recv/ackPacket``) on ``to_side``.
    Tx-hash dedup makes it idempotent.
    """

    def __init__(
        self,
        src: _Endpoint,
        dst: _Endpoint,
        grpc_address: str,
        *,
        evm_gas_limit: int = 2_000_000,
    ) -> None:
        self.src = src
        self.dst = dst
        self._client = RelayerClient(grpc_address)
        self._relayed: set[bytes] = set()
        self._evm_gas_limit = evm_gas_limit

    def close(self) -> None:
        self._client.close()

    @contextmanager
    def _relay_once(self, key: bytes, label: str, shown: bytes):
        """Dedup guard: raise if ``key`` was already relayed, else mark it for the
        duration. Un-marks on failure so a transient error stays retryable — the
        mark only sticks once the relay+submit actually succeeds (prevents a
        double-submit of the same packet)."""
        if key in self._relayed:
            raise ValueError(f"{label} {shown.hex()} already relayed")
        self._relayed.add(key)
        try:
            yield
        except Exception:
            self._relayed.discard(key)
            raise

    async def _submit_evm(
        self, to_side: _Endpoint, tx: bytes, address: str, label: str
    ) -> dict:
        """Submit a relayer-returned multicall on ``to_side``; on revert, replay
        it as ``eth_call`` to surface the reason (receipts drop it). ``address`` is
        a relayer-returned hex string — convert to an Address (HexBytes) here, the
        periphery, casing-safe; bytes are accepted by send_transaction at runtime."""
        to = HexBytes(address or to_side.router_addr)
        receipt = await send_transaction(
            to_side.w3,
            to_side.deployer,
            to=to,
            data=tx,
            gas=self._evm_gas_limit,
            check=False,
        )
        if receipt["status"] == 1:
            return dict(receipt)
        call = {"to": to, "data": tx, "from": to_side.deployer.address}
        try:
            await to_side.w3.eth.call(call, block_identifier=receipt["blockNumber"])
        except Exception as exc:
            raise RuntimeError(
                f"{label} reverted (to={to.to_0x_hex()}): {exc}"
            ) from exc
        raise RuntimeError(
            f"{label} reverted but eth_call passed (to={to.to_0x_hex()})"
        )

    async def relay(
        self, from_side: _Endpoint, to_side: _Endpoint, tx_hash: bytes
    ) -> dict:
        with self._relay_once(tx_hash, "tx", tx_hash):
            tx, address = self._client.relay_by_tx(
                src_chain=from_side.chain_id,
                dst_chain=to_side.chain_id,
                source_tx_ids=[tx_hash],
                src_client_id=from_side.client_id,
                dst_client_id=to_side.client_id,
            )
            return await self._submit_evm(to_side, tx, address, "relayer tx")

    def relay_to_cosmos(
        self,
        *,
        src_chain: str,
        dst_chain: str,
        src_client_id: str,
        dst_client_id: str,
        tx_hash: bytes,
        mantra,
        signer_name: str,
        denom: str,
    ) -> dict:
        """Relay an EVM source tx to a Cosmos destination: ``RelayByTx``
        returns an unsigned ``TxBody`` (``MsgRecvPacket``/``MsgAckPacket``)
        which we SIGN_DIRECT-sign and broadcast on ``mantra``. Returns the
        committed cosmos tx (with events). Idempotent per source tx hash.
        """
        # Local import keeps the cosmos signing deps off the EVM-only path.
        from .eureka_cosmos import sign_and_broadcast_body

        with self._relay_once(tx_hash, "tx", tx_hash):
            tx, _ = self._client.relay_by_tx(
                src_chain=src_chain,
                dst_chain=dst_chain,
                source_tx_ids=[tx_hash],
                src_client_id=src_client_id,
                dst_client_id=dst_client_id,
            )
            return sign_and_broadcast_body(mantra, signer_name, tx, denom=denom)

    def create_attestations_client(
        self,
        mantra,
        signer_name: str,
        *,
        eth_chain_id: str,
        cosmos_chain_id: str,
        attestor_addresses: list[str],
        height: int,
        timestamp: int,
        denom: str,
        min_required_sigs: int = 1,
    ) -> str:
        """Create the ibc-go ``attestations`` light client tracking the EVM chain
        via the relayer's ``CreateClient`` (src=eth, dst=cosmos); SIGN_DIRECT-sign
        the returned ``TxBody`` and broadcast it. Returns the client id."""
        from .eureka_cosmos import sign_and_broadcast_body
        from .utils import find_log_event_attrs

        tx = self._client.create_client(
            src_chain=eth_chain_id,
            dst_chain=cosmos_chain_id,
            parameters={
                "attestor_addresses": ",".join(attestor_addresses),
                "min_required_sigs": str(min_required_sigs),
                "height": str(height),
                "timestamp": str(timestamp),
            },
        )
        committed = sign_and_broadcast_body(mantra, signer_name, tx, denom=denom)
        attrs = find_log_event_attrs(committed.get("events", []), "create_client")
        client_id = (attrs or {}).get("client_id")
        assert client_id, f"no client_id in events: {committed.get('events')}"
        return client_id

    def relay_timeout_to_cosmos(
        self,
        *,
        src_chain: str,
        dst_chain: str,
        src_client_id: str,
        dst_client_id: str,
        timeout_tx_hash: bytes,
        mantra,
        signer_name: str,
        denom: str,
    ) -> dict:
        """Relay a cosmos-source packet timeout: ``RelayByTx`` with ``timeout_tx_ids``
        returns an unsigned cosmos ``MsgTimeout`` we sign + broadcast on ``mantra``
        to refund the sender (non-receipt proven on the EVM dest). Idempotent.
        """
        from .eureka_cosmos import sign_and_broadcast_body

        with self._relay_once(
            b"timeout:" + timeout_tx_hash, "timeout", timeout_tx_hash
        ):
            tx, _ = self._client.relay_by_tx(
                src_chain=src_chain,
                dst_chain=dst_chain,
                timeout_tx_ids=[timeout_tx_hash],
                src_client_id=src_client_id,
                dst_client_id=dst_client_id,
            )
            return sign_and_broadcast_body(mantra, signer_name, tx, denom=denom)

    async def relay_timeout(
        self,
        *,
        src_chain: str,
        dst_chain: str,
        src_client_id: str,
        dst_client_id: str,
        timeout_tx_hash: bytes,
        to_side: _Endpoint,
    ) -> dict:
        """Relay a timeout: ``RelayByTx`` with ``timeout_tx_ids`` returns the
        non-receipt proof + ``timeoutPacket`` multicall for the EVM source
        (``to_side``), which refunds the escrowed tokens. ``src_chain`` is the
        chain that proves non-receipt (Cosmos); ``timeout_tx_hash`` is the
        original EVM send tx whose packet timed out.
        """
        with self._relay_once(
            b"timeout:" + timeout_tx_hash, "timeout", timeout_tx_hash
        ):
            tx, address = self._client.relay_by_tx(
                src_chain=src_chain,
                dst_chain=dst_chain,
                timeout_tx_ids=[timeout_tx_hash],
                src_client_id=src_client_id,
                dst_client_id=dst_client_id,
            )
            return await self._submit_evm(to_side, tx, address, "timeout tx")

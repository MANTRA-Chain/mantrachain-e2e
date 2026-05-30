"""Mirrors ``solidity-ibc-eureka/scripts/E2ETestDeploy.s.sol``: AccessManager,
ICS26Router + ICS20Transfer (behind ERC1967 proxies), role wiring with
``pubRelay=True``, a TestERC20, and a DummyLightClient registered as a
counterparty client.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from eth_account import Account
from eth_account.signers.base import BaseAccount
from eth_contract.utils import send_transaction
from eth_utils import function_abi_to_4byte_selector
from web3 import AsyncWeb3
from web3.contract import AsyncContract

from .eureka_artifacts import get_contract

# Role IDs from solidity-ibc-eureka/contracts/utils/IBCRolesLib.sol.
ADMIN_ROLE = 0
PUBLIC_ROLE = (1 << 64) - 1
RELAYER_ROLE = 1
PAUSER_ROLE = 2
UNPAUSER_ROLE = 3
DELEGATE_SENDER_ROLE = 4
ID_CUSTOMIZER_ROLE = 6
ERC20_CUSTOMIZER_ROLE = 7

ICS20_DEFAULT_PORT = "transfer"


# ---------------------------------------------------------------------------
# Selector helpers
# ---------------------------------------------------------------------------


def _selectors_by_name(abi: list[dict], names: Sequence[str]) -> list[bytes]:
    """Resolve 4-byte selectors for the given function names in ABI order."""
    wanted = set(names)
    found: dict[str, bytes] = {}
    for entry in abi:
        if entry.get("type") != "function":
            continue
        if entry["name"] in wanted and entry["name"] not in found:
            found[entry["name"]] = function_abi_to_4byte_selector(entry)
    missing = wanted - found.keys()
    if missing:
        raise KeyError(f"functions missing from ABI: {sorted(missing)}")
    return [found[n] for n in names]


def _selectors_overload_inputs(abi: list[dict], name: str, n_inputs: int) -> bytes:
    """Pick an overloaded function's selector by input arity."""
    for entry in abi:
        if (
            entry.get("type") == "function"
            and entry["name"] == name
            and len(entry["inputs"]) == n_inputs
        ):
            return function_abi_to_4byte_selector(entry)
    raise KeyError(f"function {name} with {n_inputs} inputs not in ABI")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class DeployedEurekaStack:
    """Handles returned by :func:`deploy_eureka_stack`."""

    deployer: BaseAccount
    access_manager: AsyncContract
    ics26_router: AsyncContract
    ics20_transfer: AsyncContract
    escrow_logic: AsyncContract
    ibcerc20_logic: AsyncContract
    test_erc20: AsyncContract
    light_client: AsyncContract
    client_id: str
    counterparty_client_id: str = "07-tendermint-0"


# ---------------------------------------------------------------------------
# Internal: deploy a single contract
# ---------------------------------------------------------------------------


async def _deploy(
    w3: AsyncWeb3,
    account: BaseAccount,
    artifact_name: str,
    *args,
) -> AsyncContract:
    """Deploy a contract from the eureka artifacts registry."""
    art = get_contract(artifact_name)
    factory = w3.eth.contract(abi=art["abi"], bytecode="0x" + art["bin"])
    tx = await factory.constructor(*args).build_transaction({"from": account.address})
    receipt = await send_transaction(w3, account, **tx)
    addr = receipt["contractAddress"]
    print(f"deployed {artifact_name} at {addr}")
    return w3.eth.contract(address=addr, abi=art["abi"])


async def _send(w3: AsyncWeb3, account: BaseAccount, contract_call) -> dict:
    """Sign and send a contract call; return the receipt."""
    tx = await contract_call.build_transaction({"from": account.address})
    return await send_transaction(w3, account, **tx)


async def _deploy_proxy(
    w3: AsyncWeb3,
    deployer: BaseAccount,
    logic: AsyncContract,
    init_args: list,
    label: str,
) -> AsyncContract:
    """Deploy an ERC1967Proxy over ``logic`` (initialized with ``init_args``) and
    return it re-wrapped with the logic ABI so the impl's functions are callable."""
    init = logic.encode_abi(abi_element_identifier="initialize", args=init_args)
    proxy = await _deploy(
        w3, deployer, "ERC1967Proxy", logic.address, bytes.fromhex(init[2:])
    )
    wrapped = w3.eth.contract(address=proxy.address, abi=logic.abi)
    print(f"{label} proxy at {wrapped.address}")
    return wrapped


# ---------------------------------------------------------------------------
# Top-level entrypoint
# ---------------------------------------------------------------------------


async def deploy_eureka_stack(
    w3: AsyncWeb3,
    deployer_key: bytes | str,
    *,
    counterparty_client_id: str = "07-tendermint-0",
    light_client: tuple[str, tuple] = ("DummyLightClient", (0, 0, False)),
    merkle_prefix: list[bytes] | None = None,
) -> DeployedEurekaStack:
    """Deploy the send-side Eureka stack. ``light_client`` is
    ``(contract_name, ctor_args)``; defaults to DummyLightClient."""
    deployer = Account.from_key(deployer_key)
    print(f"deploying eureka stack from {deployer.address}")

    access_manager = await _deploy(w3, deployer, "AccessManager", deployer.address)

    # ---- Logic contracts --------------------------------------------------
    router_logic = await _deploy(w3, deployer, "ICS26Router")
    transfer_logic = await _deploy(w3, deployer, "ICS20Transfer")
    escrow_logic = await _deploy(w3, deployer, "Escrow")
    ibcerc20_logic = await _deploy(w3, deployer, "IBCERC20")

    # ---- Proxies (ERC1967 over the logic, initialized in the same tx) ------
    router = await _deploy_proxy(
        w3, deployer, router_logic, [access_manager.address], "ICS26Router"
    )
    zero_addr = w3.to_checksum_address("0x" + "00" * 20)
    transfer = await _deploy_proxy(
        w3,
        deployer,
        transfer_logic,
        [
            router.address,
            escrow_logic.address,
            ibcerc20_logic.address,
            zero_addr,  # permit2 — disabled for our tests
            access_manager.address,
        ],
        "ICS20Transfer",
    )

    await _wire_access_control(
        w3,
        deployer,
        access_manager,
        ics26=router,
        ics20=transfer,
    )

    # addIBCApp(string,address) is restricted; deployer was granted
    # ID_CUSTOMIZER_ROLE above so this call succeeds.
    receipt = await _send(
        w3, deployer, router.functions.addIBCApp(ICS20_DEFAULT_PORT, transfer.address)
    )
    assert receipt["status"] == 1, "addIBCApp failed"
    print(f"registered ICS20 app on port '{ICS20_DEFAULT_PORT}'")

    # Don't mint type(uint256).max: downstream tests mint more of this TestERC20
    # (MockV3Pool swap payouts), and OZ ERC20._update's unchecked _totalSupply
    # would panic (0x11) at the cap.
    test_erc20 = await _deploy(w3, deployer, "TestERC20")
    initial_supply = 10**30
    await _send(
        w3,
        deployer,
        test_erc20.functions.mint(deployer.address, initial_supply),
    )
    print(f"minted {initial_supply} TestERC20 to deployer")

    # Light client — DummyLightClient (single-chain, always-succeed) or
    # AttestationLightClient (cross-chain, ECDSA-verifies attestor sigs).
    light_client_name, light_client_args = light_client
    light_client_handle = await _deploy(
        w3, deployer, light_client_name, *light_client_args
    )
    client_id = await _add_client(
        w3,
        deployer,
        router,
        counterparty_client_id=counterparty_client_id,
        light_client_addr=light_client_handle.address,
        merkle_prefix=merkle_prefix if merkle_prefix is not None else [b"ibc", b""],
    )
    print(f"eureka stack ready: clientId={client_id}")

    return DeployedEurekaStack(
        deployer=deployer,
        access_manager=access_manager,
        ics26_router=router,
        ics20_transfer=transfer,
        escrow_logic=escrow_logic,
        ibcerc20_logic=ibcerc20_logic,
        test_erc20=test_erc20,
        light_client=light_client_handle,
        client_id=client_id,
        counterparty_client_id=counterparty_client_id,
    )


# ---------------------------------------------------------------------------
# Sub-steps
# ---------------------------------------------------------------------------


async def _wire_access_control(
    w3: AsyncWeb3,
    deployer: BaseAccount,
    access_manager: AsyncContract,
    *,
    ics26: AsyncContract,
    ics20: AsyncContract,
) -> None:
    """Apply role assignments for the router and transfer apps (pubRelay=True)."""
    ics26_abi = ics26.abi
    ics20_abi = ics20.abi

    # addIBCApp/addClient are overloaded; the *restricted* variants take
    # 2 and 3 inputs respectively (the public variants take 1 and 2).
    id_customizer_selectors = [
        _selectors_overload_inputs(ics26_abi, "addIBCApp", 2),
        _selectors_overload_inputs(ics26_abi, "addClient", 3),
    ]
    relayer_selectors = _selectors_by_name(
        ics26_abi, ["recvPacket", "timeoutPacket", "ackPacket", "updateClient"]
    )
    pauser_selectors = _selectors_by_name(ics20_abi, ["pause"])
    unpauser_selectors = _selectors_by_name(ics20_abi, ["unpause"])
    erc20_customizer_selectors = _selectors_by_name(ics20_abi, ["setCustomERC20"])
    delegate_sender_selectors = _selectors_by_name(
        ics20_abi, ["sendTransferWithSender"]
    )
    transfer_beacon_upgrade_selectors = _selectors_by_name(
        ics20_abi, ["upgradeEscrowTo", "upgradeIBCERC20To"]
    )
    uups_upgrade_selectors_router = _selectors_by_name(ics26_abi, ["upgradeToAndCall"])
    uups_upgrade_selectors_transfer = _selectors_by_name(
        ics20_abi, ["upgradeToAndCall"]
    )

    setrole = access_manager.functions.setTargetFunctionRole
    grantrole = access_manager.functions.grantRole

    # Role assignments per accessManagerSetTargetRoles (pubRelay=True path).
    role_calls = [
        setrole(ics26.address, id_customizer_selectors, ID_CUSTOMIZER_ROLE),
        # pubRelay=True → relayer selectors granted to PUBLIC_ROLE (no role grant
        # needed for relayers to call recvPacket / ackPacket / timeoutPacket).
        setrole(ics26.address, relayer_selectors, PUBLIC_ROLE),
        setrole(ics20.address, pauser_selectors, PAUSER_ROLE),
        setrole(ics20.address, unpauser_selectors, UNPAUSER_ROLE),
        setrole(ics20.address, erc20_customizer_selectors, ERC20_CUSTOMIZER_ROLE),
        setrole(ics20.address, delegate_sender_selectors, DELEGATE_SENDER_ROLE),
        setrole(ics20.address, transfer_beacon_upgrade_selectors, ADMIN_ROLE),
        setrole(ics20.address, uups_upgrade_selectors_transfer, ADMIN_ROLE),
        setrole(ics26.address, uups_upgrade_selectors_router, ADMIN_ROLE),
    ]
    for call in role_calls:
        receipt = await _send(w3, deployer, call)
        assert receipt["status"] == 1, "setTargetFunctionRole failed"
    print(f"wired {len(role_calls)} target-role assignments")

    # The deployer only needs ID_CUSTOMIZER_ROLE (it calls addIBCApp + addClient).
    # Other roles are wired via setTargetFunctionRole to match upstream but granted
    # to no one — no test exercises them.
    receipt = await _send(
        w3, deployer, grantrole(ID_CUSTOMIZER_ROLE, deployer.address, 0)
    )
    assert receipt["status"] == 1, "grantRole(ID_CUSTOMIZER_ROLE) failed"
    print("granted deployer ID_CUSTOMIZER_ROLE")


async def _add_client(
    w3: AsyncWeb3,
    deployer: BaseAccount,
    router: AsyncContract,
    *,
    counterparty_client_id: str,
    light_client_addr: str,
    merkle_prefix: list[bytes],
) -> str:
    """Register a counterparty client via the public overload; return local clientId."""
    counterparty_info = (counterparty_client_id, merkle_prefix)  # (clientId, prefix)
    add_fn = router.get_function_by_signature("addClient((string,bytes[]),address)")
    receipt = await _send(w3, deployer, add_fn(counterparty_info, light_client_addr))
    assert receipt["status"] == 1, "addClient failed"

    logs = router.events.ICS02ClientAdded().process_receipt(receipt)
    assert len(logs) == 1, f"expected 1 ICS02ClientAdded, got {len(logs)}"
    client_id = logs[0]["args"]["clientId"]
    print(f"added client {client_id} (counterparty={counterparty_client_id})")
    return client_id

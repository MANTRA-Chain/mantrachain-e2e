import datetime
import json
import shutil
from contextlib import contextmanager
from dataclasses import astuple
from pathlib import Path

import pytest
import requests
import tomlkit
from eth_abi.abi import decode, encode
from eth_account import Account
from eth_contract.contract import Contract
from eth_contract.create2 import create2_address
from eth_contract.deploy_utils import (
    ensure_create2_deployed,
    ensure_deployed_by_create2,
)
from eth_contract.utils import get_initcode
from eth_hash.auto import keccak
from pystarport import cluster, ports
from pystarport.utils import (
    wait_for_fn,
    wait_for_new_blocks,
    wait_for_port,
)
from web3.logs import DISCARD

from .doc_utils import (
    DOCUMENT_ADDRESS,
    DOCUMENT_PRECOMPILE,
    Record,
    Role,
    _tx_params,
    add_record,
    clear_accounts_override,
    consumer_eip1559_fees,
    do_test_add_and_query_records,
    do_test_add_record,
    do_test_add_record_same_checksum_maintains_record_id,
    do_test_add_registry,
    do_test_checksum_only_query_respects_limit,
    do_test_constructor_bypass_ensure_eoa_caller,
    do_test_contract_cannot_call_anchoring_sensitive_methods,
    do_test_disallow_last_admin_self_revoke,
    do_test_grant_and_revoke_role_as_admin,
    do_test_grant_role_permissions,
    do_test_module_admin_emergency_admin_recovery,
    do_test_multiple_roles_management,
    do_test_multiple_versions_same_checksum_across_registries,
    do_test_query_all_registries_for_checksum,
    do_test_query_by_registry_and_checksum,
    do_test_record_level_overrides_registry_level,
    do_test_registry_only_query_respects_limit,
    do_test_revoke_role_permissions,
    do_test_role_idempotency,
    do_test_role_scope_existence_validation,
    do_test_role_with_different_checksums,
    do_test_same_checksum_different_record_ids_per_registry,
    do_test_shared_checksum_in_multi_registries,
    ensure_registry_exists,
    get_accounts,
    get_add_registry_event_registry_id,
    set_accounts_override,
    sha256_hex,
)
from .ibc_utils import IBCNetwork, create_channel, create_connection, ibc_denom_hash
from .network import Hermes, Mantra, setup_custom_mantra
from .utils import (
    ADDRS,
    CMD,
    CONSUMER_GAS_AMT,
    DEFAULT_DENOM,
    KEYS,
    MNEMONICS,
    MockERC20_ARTIFACT,
    assert_estimate_covers_receipt,
    assert_gas_estimate_within_floor,
    build_contract,
    create_consumer_chain,
    eth_to_bech32,
    find_log_event_attrs,
    ibc_denom_address,
    module_address,
    multisig_sign_and_broadcast,
    send_transaction,
    setup_multisig,
    update_consumer_chain,
)

pytestmark = pytest.mark.ccv

TRANSFER_CHANNEL_ID = "channel-1"
MANTRAUSD_CREATE2_SALT = 1
WMANTRAUSD_CREATE2_SALT = 2
PRED_MANTRAUSD_ADDR = create2_address(
    get_initcode(MockERC20_ARTIFACT, "mantraUSD", "mUSD", 6),
    MANTRAUSD_CREATE2_SALT,
)
PRED_WMANTRAUSD_ADDR = create2_address(
    get_initcode(build_contract("wmantraUSD"), PRED_MANTRAUSD_ADDR),
    WMANTRAUSD_CREATE2_SALT,
)
WMANTRAUSD_DENOM = f"erc20:{PRED_WMANTRAUSD_ADDR}"


def wmantrausd_consumer_ibc_denom(transfer_channel_id: str) -> str:
    return f"ibc/{ibc_denom_hash(f'transfer/{transfer_channel_id}/{WMANTRAUSD_DENOM}')}"


# ibc/88C1928A7164E0F5166D1D1585A3167FF6B19C2F25CA4D3636941FFF1BC19B80
WMANTRAUSD_CONSUMER_IBC_DENOM = wmantrausd_consumer_ibc_denom(TRANSFER_CHANNEL_ID)

# tokenfactory denom used by test_provider_bank_hooks_fire_on_reward_distribution.
# Pre-computed so it can be added to the consumer's allowlist at fixture setup
# (the consumer's owner becomes gov after that, so further updates are gated).
FACTORY_REWARD_SUBDENOM = "rewardhook"
FACTORY_REWARD_DENOM = (
    f"factory/{eth_to_bech32(ADDRS['validator'])}/{FACTORY_REWARD_SUBDENOM}"
)
# mantraUSD (6 decimals) <-> wmantraUSD (18 decimals)
SCALAR = 10**12
ICS20_PRECOMPILE = Contract(build_contract("ICS20I")["abi"])
ICS20_ADDRESS = "0x0000000000000000000000000000000000000802"
DISTRIBUTION_CLAIM_ADDRESS = "0x0000000000000000000000000000000000000a01"
DISTRIBUTION_ADDRESS = "0x0000000000000000000000000000000000000801"
DISTRIBUTION_CLAIM_SIG = "claimRewardsAndConvertCoin(address,uint32,string)"


def distribution_claim_call_data(
    delegator_evm: str, max_retrieve: int, denom: str
) -> str:
    selector = keccak(DISTRIBUTION_CLAIM_SIG.encode())[:4]
    args = encode(["address", "uint32", "string"], [delegator_evm, max_retrieve, denom])
    return "0x" + (selector + args).hex()


def ibc_timeout_ns(minutes: int = 10) -> int:
    return int(
        (
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=minutes)
        ).timestamp()
        * 1_000_000_000
    )


def intrinsic_calldata_gas(tx_data: str | bytes) -> int:
    if isinstance(tx_data, str):
        raw = tx_data[2:] if tx_data.startswith("0x") else tx_data
        data = bytes.fromhex(raw)
    else:
        data = bytes(tx_data)

    intrinsic = 21_000
    for b in data:
        intrinsic += 4 if b == 0 else 16
    return intrinsic


async def run_method(
    async_w3,
    sender_account,
    *,
    call,
    gas: int,
    method: str,
    deltas: dict | None = None,
):
    txp = await _tx_params(
        async_w3,
        gas=gas,
        sender=sender_account.address,
        to=DOCUMENT_ADDRESS,
        data=call.data,
    )
    receipt = await call.transact(
        async_w3,
        sender_account,
        to=DOCUMENT_ADDRESS,
        **txp,
    )
    assert receipt.status == 1
    intrinsic = intrinsic_calldata_gas(call.data)
    gas_used = int(receipt["gasUsed"])
    delta = gas_used - intrinsic
    assert (
        gas_used > intrinsic
    ), f"expected gasUsed={gas_used} > intrinsic={intrinsic} for {method}"
    assert delta > 0, f"expected positive delta for {method}, got {delta}"
    if deltas is not None:
        deltas[method] = delta
    return receipt, delta


def find_open_transfer_channel_id(cli) -> str | None:
    try:
        for ch in cli.ibc_query_all_channels():
            if ch.get("port_id") != "transfer":
                continue
            channel_id = ch.get("channel_id")
            if channel_id and check_channel_ready(cli, "transfer", channel_id):
                return channel_id
    except Exception:
        return None
    return None


@pytest.fixture(scope="function")
def setup_consumer_accounts(ibc):
    consumer_accounts = {
        name: Account.from_mnemonic(mnemonic) for name, mnemonic in MNEMONICS.items()
    }
    set_accounts_override(consumer_accounts)
    yield
    clear_accounts_override()


@pytest.fixture(scope="module")
def ibc(request, tmp_path_factory):
    b_chain_cmd = "nvnmchaind"
    if shutil.which(b_chain_cmd) is None:
        pytest.skip(f"{b_chain_cmd} not enabled")
    chain = request.config.getoption("chain_config")
    name = "configs/ibc_nvnmchaind.jsonnet"
    path = tmp_path_factory.mktemp("ibc_nvnmchaind")
    b_chain = "nvnm-canary-net-1"
    with contextmanager(setup_custom_mantra)(
        path,
        27400,
        Path(__file__).parent / name,
        relayer=cluster.Relayer.HERMES.value,
        chain=chain,
        chain_binary=f"{CMD},{b_chain_cmd}",
    ) as ibc1:
        num_nodes = 3
        ibc2 = Mantra(ibc1.base_dir.parent / b_chain, chain_binary=b_chain_cmd)
        nodes = [f"{b_chain}-node{i}" for i in range(num_nodes)]
        ibc2.supervisorctl("stop", *nodes)
        cli = ibc1.cosmos_cli()
        # wait for grpc ready
        wait_for_port(ports.grpc_port(ibc1.base_port(0)))
        wait_for_new_blocks(cli, 1)

        consumer_id = create_consumer_chain(cli, b_chain, from_="validator")

        for i in range(num_nodes):
            rsp = ibc1.cosmos_cli(i=i).provider_opt_in(consumer_id, from_="validator")
            assert rsp["code"] == 0, rsp["raw_log"]

        authority = module_address("gov")
        port = "transfer"
        channel = TRANSFER_CHANNEL_ID
        denom = WMANTRAUSD_CONSUMER_IBC_DENOM
        denom_hash = ibc_denom_hash(f"{port}/{channel}/{denom}")
        owner_address = cli.address("validator")

        # consumer native denom (as `ibc/<hash>` on the provider)
        # bridge wmantraUSD rewards that unwrap back to `erc20:<addr>` on provider
        # FACTORY_REWARD_DENOM is included for the bank-hooks regression test;
        # adding it here avoids a second update_consumer_chain call (which would
        # be unauthorized once owner has been transferred to gov below).
        allowlisted_reward_denoms = [
            f"ibc/{denom_hash}",
            WMANTRAUSD_DENOM,
            FACTORY_REWARD_DENOM,
        ]
        update_consumer_chain(
            cli,
            consumer_id,
            path,
            owner_address,
            authority,
            allowlisted_reward_denoms={"denoms": allowlisted_reward_denoms},
            from_="validator",
        )

        wait_for_new_blocks(cli, 1)

        consumer_genesis = cli.provider_consumer_genesis(consumer_id)
        now = datetime.datetime.now(datetime.UTC)

        for i in range(num_nodes):
            cons_node_dir = ibc2.base_dir / f"node{i}"
            prov_node_dir = ibc1.base_dir / f"node{i}"
            cons_cfg = cons_node_dir / "config"
            prov_cfg = prov_node_dir / "config"

            # genesis
            genesis_path = cons_cfg / "genesis.json"
            with open(genesis_path) as f:
                genesis = json.load(f)
            genesis["genesis_time"] = now.isoformat().replace("+00:00", "Z")
            genesis["app_state"]["ccvconsumer"] = consumer_genesis
            genesis["app_state"]["ccvconsumer"]["params"]["reward_denoms"] = [
                WMANTRAUSD_CONSUMER_IBC_DENOM,
            ]
            # make rewards transmission frequent for faster rewards
            genesis["app_state"]["ccvconsumer"]["params"][
                "blocks_per_distribution_transmission"
            ] = "1"
            # keep reward transfer timeout short for timeout refund test
            genesis["app_state"]["ccvconsumer"]["params"][
                "transfer_timeout_period"
            ] = "10s"
            genesis["app_state"]["feemarket"]["params"]["base_fee"] = "87600000000"
            genesis["app_state"]["feemarket"]["params"]["min_gas_price"] = "87600000000"
            with open(cons_cfg / "edited_genesis.json", "w") as f:
                json.dump(genesis, f, indent=2)
            (cons_cfg / "edited_genesis.json").replace(genesis_path)

            # priv val state
            state_path = cons_node_dir / "data" / "priv_validator_state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(state_path, "w") as f:
                json.dump({"height": "0", "round": 0, "step": 0}, f)

            # keys
            for name in ["priv_validator_key.json", "node_key.json"]:
                shutil.copy2(prov_cfg / name, cons_cfg / name)

            # peers
            peers = ",".join(
                f"tcp://{ibc1.cosmos_cli(i=j).node_id()}@127.0.0.1:{ports.p2p_port(ibc2.base_port(j))}"  # noqa: E501
                for j in range(num_nodes)
                if j != i
            )
            config_path = cons_cfg / "config.toml"
            with open(config_path) as f:
                doc = tomlkit.parse(f.read())
            doc["p2p"]["persistent_peers"] = peers
            with open(config_path, "w") as f:
                f.write(tomlkit.dumps(doc))

            app_config_path = cons_cfg / "app.toml"
            with open(app_config_path) as f:
                app_doc = tomlkit.parse(f.read())
            # allow paying fees with bridged wmantraUSD IBC denom
            app_doc["minimum-gas-prices"] = f"0{WMANTRAUSD_CONSUMER_IBC_DENOM}"
            with open(app_config_path, "w") as f:
                f.write(tomlkit.dumps(app_doc))

        ibc2.supervisorctl("start", *nodes)

        wait_for_port(ports.grpc_port(ibc2.base_port(0)))
        wait_for_new_blocks(ibc2.cosmos_cli(), 1)

        path = ibc1.base_dir.parent / "relayer"
        hermes = Hermes(path.with_suffix(".toml"))
        create_connection(hermes, b_chain)
        create_channel(hermes, b_chain, "consumer", "provider")

        ibc1.supervisorctl("start", "relayer-demo")
        # Delegate tokens to validator and relay the resulting VSC packet to consumer
        res = cli.delegations(owner_address)
        val = res[0]["delegation"]["validator_address"]
        delegate_amt = 10000000000000000000
        gas = 350_000
        coin = f"{delegate_amt}{DEFAULT_DENOM}"
        rsp = cli.delegate_amount(val, coin, _from="validator", gas=gas)
        assert rsp["code"] == 0, rsp["raw_log"]

        cli2 = ibc2.cosmos_cli()

        def extract_voting_power(valset):
            return [v["voting_power"] for v in valset["validators"]]

        def check_voting_power():
            vp = extract_voting_power(cli.comet_validator_set(0))
            vp2 = extract_voting_power(cli2.comet_validator_set(0))
            return vp == vp2

        wait_for_fn("voting_power should match", check_voting_power, timeout=30)

        yield IBCNetwork(ibc1, ibc2, hermes)
        wait_for_port(hermes.port)


def check_channel_ready(cli, port_id: str, channel_id: str) -> bool:
    try:
        res = cli.ibc_query_channel(port_id, channel_id).get("channel")
    except Exception as e:
        print(f"{port_id}/{channel_id} not ready: {e}")
        res = None
    return res is not None and res.get("state") == "STATE_OPEN"


async def test_ccv(ibc):
    cli = ibc.ibc1.cosmos_cli()
    cli2 = ibc.ibc2.cosmos_cli()
    provider_channel = "channel-0"
    res = cli.ibc_query_channel("provider", provider_channel).get("channel")
    assert res.get("state") == "STATE_OPEN"

    wait_for_fn(
        "channel ready",
        lambda: check_channel_ready(cli, "transfer", TRANSFER_CHANNEL_ID),
        timeout=30,
    )

    def check_provider_ready():
        try:
            res = cli2.query_provider_info()
            return res.get("provider", {}).get("channelID") == provider_channel
        except Exception as e:
            print(f"provider not ready: {e}")
            return False

    wait_for_fn("provider ready", check_provider_ready, timeout=30)

    w3 = ibc.ibc2.w3
    community = "community"
    signer = "signer2"
    sender = ADDRS[community]
    receiver = ADDRS[signer]
    balance_bf = w3.eth.get_balance(receiver)
    amt = 1000
    receipt = send_transaction(
        w3,
        {
            "from": sender,
            "to": receiver,
            "value": amt,
            **consumer_eip1559_fees(w3),
        },
        KEYS[community],
    )
    balance = w3.eth.get_balance(receiver)
    assert receipt.status == 1
    assert balance - balance_bf == amt
    amt = 2000
    denom = WMANTRAUSD_CONSUMER_IBC_DENOM
    rsp = cli2.transfer(
        cli2.address(community),
        cli2.address(signer),
        f"{amt}{denom}",
        gas_prices=f"{CONSUMER_GAS_AMT}{denom}",
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    assert w3.eth.get_balance(receiver) - balance == amt


async def test_wmantrausd_bridge_deposit_to_consumer(ibc):
    provider_cli, consumer_cli = ibc.ibc1.cosmos_cli(), ibc.ibc2.cosmos_cli()

    def channel_ready() -> bool:
        return all(
            find_open_transfer_channel_id(cli) is not None
            for cli in (consumer_cli, provider_cli)
        )

    wait_for_fn("transfer channels open", channel_ready, timeout=60)

    consumer_transfer_channel = find_open_transfer_channel_id(consumer_cli)
    provider_transfer_channel = find_open_transfer_channel_id(provider_cli)
    assert consumer_transfer_channel == provider_transfer_channel == TRANSFER_CHANNEL_ID

    sender_name = "community"
    sender = ADDRS[sender_name]
    sender_key = KEYS[sender_name]
    w3 = ibc.ibc1.w3
    async_w3 = ibc.ibc1.async_w3

    receiver_name = "signer2"
    receiver_bech32 = consumer_cli.address(receiver_name)

    funder_acct = Account.from_key(sender_key)
    await ensure_create2_deployed(async_w3, funder_acct)

    # 1) Deploy 6-decimal mantraUSD and mint to sender
    mantrausd_initcode = get_initcode(MockERC20_ARTIFACT, "mantraUSD", "mUSD", 6)
    mantrausd_addr = await ensure_deployed_by_create2(
        async_w3,
        funder_acct,
        mantrausd_initcode,
        salt=MANTRAUSD_CREATE2_SALT,
        gas=3_000_000,
    )
    assert w3.to_checksum_address(mantrausd_addr) == PRED_MANTRAUSD_ADDR
    mantrausd = w3.eth.contract(address=mantrausd_addr, abi=MockERC20_ARTIFACT["abi"])

    amt_mantrausd = 1_000_000  # 1.0 with 6 decimals
    mint_receipt = send_transaction(
        w3,
        mantrausd.functions.mint(sender, amt_mantrausd).build_transaction(
            {"from": sender, "gas": 200_000}
        ),
        sender_key,
    )
    assert mint_receipt.status == 1

    # 2) Deploy wmantraUSD
    w_res = build_contract("wmantraUSD")
    w_initcode = get_initcode(w_res, mantrausd.address)
    wmantrausd_addr = await ensure_deployed_by_create2(
        async_w3,
        funder_acct,
        w_initcode,
        salt=WMANTRAUSD_CREATE2_SALT,
        gas=6_000_000,
    )
    assert w3.to_checksum_address(wmantrausd_addr) == PRED_WMANTRAUSD_ADDR
    wmantrausd = w3.eth.contract(address=wmantrausd_addr, abi=w_res["abi"])

    wmantrausd_addr = w3.to_checksum_address(wmantrausd.address)

    # 3) Approve + deposit
    approve_receipt = send_transaction(
        w3,
        mantrausd.functions.approve(
            wmantrausd.address, amt_mantrausd
        ).build_transaction({"from": sender, "gas": 200_000}),
        sender_key,
    )
    assert approve_receipt.status == 1

    deposit_receipt = send_transaction(
        w3,
        wmantrausd.functions.depositFor(sender, amt_mantrausd).build_transaction(
            {"from": sender, "gas": 500_000}
        ),
        sender_key,
    )
    assert deposit_receipt.status == 1

    assert wmantrausd.functions.balanceOf(sender).call() >= amt_mantrausd * SCALAR

    register_tx = provider_cli.register_erc20(
        wmantrausd_addr,
        _from=sender_name,
        gas=3_000_000,
    )
    assert register_tx.get("code", 0) == 0, register_tx.get("logs", "")

    pair_rsp = provider_cli.query_erc20_token_pair(wmantrausd_addr)
    assert pair_rsp and wmantrausd_addr.lower() in str(pair_rsp).lower(), pair_rsp

    erc20_denom = f"erc20:{wmantrausd_addr}"
    ibc_denom = wmantrausd_consumer_ibc_denom(consumer_transfer_channel)

    assert erc20_denom == WMANTRAUSD_DENOM
    assert ibc_denom == WMANTRAUSD_CONSUMER_IBC_DENOM

    amt_wmantrausd = amt_mantrausd * SCALAR
    expected = consumer_cli.balance(receiver_bech32, denom=ibc_denom) + amt_wmantrausd

    # 4) Ensure sender starts with 0 `erc20:<addr>` before MsgTransfer auto-converts.
    sender_bech32 = provider_cli.address(sender_name)
    assert provider_cli.balance(sender_bech32, denom=erc20_denom) == 0

    # 5) ICS20 transfer to consumer
    timeout_ns = ibc_timeout_ns()
    ics20_call = ICS20_PRECOMPILE.fns.transfer(
        "transfer",
        provider_transfer_channel,
        erc20_denom,
        amt_wmantrausd,
        sender,
        receiver_bech32,
        (0, 0),
        timeout_ns,
        "",
    )
    base_fee = int(w3.eth.get_block("latest")["baseFeePerGas"])
    priority_fee = 2_000_000_000
    ics20_receipt = send_transaction(
        w3,
        {
            "to": ICS20_ADDRESS,
            "data": ics20_call.data,
            "gas": 3_000_000,
            "maxFeePerGas": base_fee * 2 + priority_fee,
            "maxPriorityFeePerGas": priority_fee,
        },
        sender_key,
    )
    assert ics20_receipt.status == 1

    # Assert convert ERC20 Transfer and precompile's IBCTransfer event
    transfer_logs = wmantrausd.events.Transfer().process_receipt(
        ics20_receipt, errors=DISCARD
    )
    assert any(
        ev.args["from"].lower() == sender.lower() and ev.args.value == amt_wmantrausd
        for ev in transfer_logs
    ), "wmantraUSD Transfer from sender not emitted during convert"

    ics20_contract = w3.eth.contract(
        address=ICS20_ADDRESS, abi=build_contract("ICS20I")["abi"]
    )
    ibc_logs = ics20_contract.events.IBCTransfer().process_receipt(
        ics20_receipt, errors=DISCARD
    )
    assert len(ibc_logs) == 1, f"expected 1 IBCTransfer event, got {len(ibc_logs)}"
    ev = ibc_logs[0].args
    assert ev.sender.lower() == sender.lower()
    assert ev.sourcePort == "transfer"
    assert ev.sourceChannel == provider_transfer_channel
    assert ev.denom == erc20_denom
    assert ev.amount == amt_wmantrausd

    def received() -> bool:
        return consumer_cli.balance(receiver_bech32, denom=ibc_denom) >= expected

    wait_for_fn("wmantraUSD bridged balance", received, timeout=60)
    assert consumer_cli.balance(receiver_bech32, denom=ibc_denom) == expected

    # 6) Reverse flow: send `ibc/<hash>` back to provider.
    # Provider transfer middleware auto-converts returned `erc20:<addr>` bank coins into
    # their ERC20 form (convert-coin) when the receiver is an EVM hex address.
    # with `{"mantra":{"unwrap":true}}` memo, provider will also best-effort unwrap
    # wrapper ERC20s (wmantraUSD) into the underlying (mantraUSD).
    receiver_evm = ADDRS[receiver_name]
    return_amt_wmantrausd = 10**15
    assert (
        consumer_cli.balance(receiver_bech32, denom=ibc_denom) > return_amt_wmantrausd
    )

    provider_wmantrausd_bal_bf = wmantrausd.functions.balanceOf(receiver_evm).call()
    provider_mantrausd_bal_bf = mantrausd.functions.balanceOf(receiver_evm).call()
    consumer_ibc_bal_bf = consumer_cli.balance(receiver_bech32, denom=ibc_denom)

    unwrap_memo = json.dumps({"mantra": {"unwrap": True}})
    timeout_ns = ibc_timeout_ns()
    ics20_return_call = ICS20_PRECOMPILE.fns.transfer(
        "transfer",
        consumer_transfer_channel,
        ibc_denom,
        return_amt_wmantrausd,
        receiver_evm,
        receiver_evm,
        (0, 0),
        timeout_ns,
        unwrap_memo,
    )
    ics20_return_receipt = send_transaction(
        ibc.ibc2.w3,
        {
            "to": ICS20_ADDRESS,
            "data": ics20_return_call.data,
            "gas": 3_000_000,
            **consumer_eip1559_fees(ibc.ibc2.w3),
        },
        KEYS[receiver_name],
    )
    assert ics20_return_receipt.status == 1

    # Consumer-side precompile emitted the return-leg IBCTransfer event.
    consumer_ics20 = ibc.ibc2.w3.eth.contract(
        address=ICS20_ADDRESS, abi=build_contract("ICS20I")["abi"]
    )
    return_logs = consumer_ics20.events.IBCTransfer().process_receipt(
        ics20_return_receipt, errors=DISCARD
    )
    assert len(return_logs) == 1
    rev = return_logs[0].args
    assert rev.sender.lower() == receiver_evm.lower()
    assert rev.sourceChannel == consumer_transfer_channel
    assert rev.denom == ibc_denom
    assert rev.amount == return_amt_wmantrausd
    assert rev.memo == unwrap_memo

    # Consumer spent at least `return_amt_wmantrausd` (plus fees).
    assert (
        consumer_cli.balance(receiver_bech32, denom=ibc_denom)
        <= consumer_ibc_bal_bf - return_amt_wmantrausd
    )

    expected_min_unwrapped = return_amt_wmantrausd // SCALAR

    def provider_received_unwrapped() -> bool:
        w_after = wmantrausd.functions.balanceOf(receiver_evm).call()
        m_after = mantrausd.functions.balanceOf(receiver_evm).call()
        w_delta = w_after - provider_wmantrausd_bal_bf
        m_delta = m_after - provider_mantrausd_bal_bf

        # unwrap should yield underlying tokens
        # with only dust (< SCALAR) left as wrapper
        return m_delta >= expected_min_unwrapped and 0 <= w_delta < SCALAR

    wait_for_fn("provider mantraUSD after unwrap", provider_received_unwrapped)

    # 7) DistributionClaim precompile smoke test
    signer1, signer1_evm = provider_cli.address("signer1"), ADDRS["signer1"]
    val = provider_cli.address("validator", "val")

    # stake large enough to receive a meaningful share of fees
    signer1_bal = provider_cli.balance(signer1, denom=DEFAULT_DENOM)
    delegate_amt = min(10**18, max(20_000_000, signer1_bal // 2))
    rsp = provider_cli.delegate_amount(
        val,
        f"{delegate_amt}{DEFAULT_DENOM}",
        _from=signer1,
        gas=250_000,
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    wait_for_new_blocks(provider_cli, 10)

    # withdraw address must equal delegator for this precompile.
    assert (
        provider_cli.distribution_withdraw_address(delegator_address=signer1) == signer1
    )

    max_retrieve = 10
    block_gas_limit = int(w3.eth.get_block("latest")["gasLimit"])
    # unwrap may do extra work; stay under the block gas limit
    gas_limit = min(12_000_000, max(1_000_000, block_gas_limit - 500_000))

    # require(withdrawAddr == delegator)
    signer2 = provider_cli.address("signer2")
    rsp = provider_cli.set_withdraw_addr(signer2, from_=signer1, gas=200_000)
    assert rsp["code"] == 0, rsp["raw_log"]
    assert (
        provider_cli.distribution_withdraw_address(delegator_address=signer1) == signer2
    )

    bad_claim_data = distribution_claim_call_data(
        signer1_evm,
        max_retrieve,
        erc20_denom,
    )
    bad_claim_convert_receipt = send_transaction(
        w3,
        {
            "to": DISTRIBUTION_CLAIM_ADDRESS,
            "data": bad_claim_data,
            "gas": gas_limit,
        },
        KEYS["signer1"],
    )
    assert bad_claim_convert_receipt.status == 0
    assert provider_cli.balance(signer1, denom=erc20_denom) == 0

    # proceed with the happy-path claim+convert
    rsp = provider_cli.set_withdraw_addr(signer1, from_=signer1, gas=200_000)
    assert rsp["code"] == 0, rsp["raw_log"]
    assert (
        provider_cli.distribution_withdraw_address(delegator_address=signer1) == signer1
    )

    # generate consumer-side fees so CCV rewards cross `SCALAR` (1e12)
    # unwrap happens when `m_delta = expected_converted // SCALAR > 0`
    unwrap_threshold = SCALAR
    high_gas = 1_000_000
    fee_txs = 2
    high_gas_price = unwrap_threshold // fee_txs  # 5e11 `ibc_denom` base units per gas
    consumer_ibc_bal_fee_bf = consumer_cli.balance(receiver_bech32, denom=ibc_denom)
    for _ in range(fee_txs):
        fee_pay_rsp = consumer_cli.transfer(
            receiver_bech32,
            receiver_bech32,
            f"1{ibc_denom}",
            gas=high_gas,
            gas_prices=f"{high_gas_price}{ibc_denom}",
        )
        assert fee_pay_rsp["code"] == 0, fee_pay_rsp["raw_log"]
    consumer_ibc_bal_fee_af = consumer_cli.balance(receiver_bech32, denom=ibc_denom)
    assert consumer_ibc_bal_fee_af < consumer_ibc_bal_fee_bf
    wait_for_new_blocks(consumer_cli, 5)
    wait_for_new_blocks(provider_cli, 5)

    def expected_converted_now() -> int:
        data = distribution_claim_call_data(
            signer1_evm,
            max_retrieve,
            erc20_denom,
        )
        res = decode(
            ["uint256"],
            w3.eth.call(
                {
                    "to": DISTRIBUTION_CLAIM_ADDRESS,
                    "from": signer1_evm,
                    "data": data,
                    "gas": gas_limit,
                }
            ),
        )
        return res[0]

    wait_for_fn(
        "expected_converted >= SCALAR",
        lambda: expected_converted_now() >= SCALAR,
    )

    bal_wmantrausd_bf = wmantrausd.functions.balanceOf(signer1_evm).call()
    bal_mantrausd_bf = mantrausd.functions.balanceOf(signer1_evm).call()

    # Claim+convert happens atomically in a single tx (all-or-nothing).
    # This checks we don't end up with a leftover `erc20:<addr>` bank coin.
    assert provider_cli.balance(signer1, denom=erc20_denom) == 0

    claim_data = distribution_claim_call_data(
        signer1_evm,
        max_retrieve,
        erc20_denom,
    )

    expected_converted = expected_converted_now()
    assert expected_converted > 0

    # claim + convert for the wmantraUSD token-pair denom
    claim_convert_receipt = send_transaction(
        w3,
        {
            "to": DISTRIBUTION_CLAIM_ADDRESS,
            "data": claim_data,
            "gas": gas_limit,
        },
        KEYS["signer1"],
    )
    assert claim_convert_receipt.status == 1

    event_sig = "ClaimRewardsAndConvertCoin(address,string,uint256)"
    event_topic0 = keccak(event_sig.encode())
    signer1_topic = (bytes.fromhex(signer1_evm[2:])).rjust(32, b"\x00")

    receipt = w3.eth.get_transaction_receipt(claim_convert_receipt.transactionHash)
    logs = [
        log
        for log in receipt["logs"]
        if log["address"].lower() == DISTRIBUTION_CLAIM_ADDRESS.lower()
        and len(log["topics"]) >= 2
        and bytes(log["topics"][0]) == event_topic0
    ]
    assert len(logs) == 1
    log = logs[0]
    assert bytes(log["topics"][1]) == signer1_topic
    ev_denom, ev_amount = decode(
        ["string", "uint256"],
        bytes(log["data"]),
    )
    assert ev_denom == erc20_denom
    assert ev_amount > 0

    bal_wmantrausd_af = wmantrausd.functions.balanceOf(signer1_evm).call()
    bal_mantrausd_af = mantrausd.functions.balanceOf(signer1_evm).call()

    w_delta = bal_wmantrausd_af - bal_wmantrausd_bf
    m_delta = bal_mantrausd_af - bal_mantrausd_bf

    assert w_delta >= 0
    assert m_delta >= 0

    converted_total = w_delta + (m_delta * SCALAR)
    assert converted_total == ev_amount
    assert converted_total >= expected_converted

    if m_delta > 0:
        # Unwrap happened: only dust (< SCALAR) should remain as wmantraUSD.
        assert w_delta < SCALAR
    else:
        # No unwrap: all converted amount remains as wrapper.
        assert m_delta == 0
        assert w_delta == ev_amount
    assert provider_cli.balance(signer1, denom=erc20_denom) == 0

    # restore default withdraw address
    rsp = provider_cli.set_withdraw_addr(signer1, from_=signer1, gas=200_000)
    assert rsp["code"] == 0, rsp["raw_log"]

    # native-denom rewards can be claimed (without conversion)
    distribution = w3.eth.contract(
        address=DISTRIBUTION_ADDRESS,
        abi=build_contract("DistributionI")["abi"],
    )
    claim_receipt = send_transaction(
        w3,
        distribution.functions.claimRewards(
            signer1_evm,
            max_retrieve,
        ).build_transaction({"from": signer1_evm, "gas": gas_limit}),
        KEYS["signer1"],
    )

    assert claim_receipt.status == 1


@pytest.mark.skip(reason="test_gov_arbitrary_message_proposal_rejected_in_ccv")
def test_gov_arbitrary_message_proposal_rejected_in_ccv(ibc, tmp_path):
    cli = ibc.ibc2.cosmos_cli()
    gov_addr = module_address("gov", prefix="nvnm")
    receiver = cli.address("community")

    proposal = {
        "title": "arbitrary-msgsend-acceptance",
        "summary": "arbitrary-msgsend-acceptance",
        "deposit": f"1{WMANTRAUSD_CONSUMER_IBC_DENOM}",
        "messages": [
            {
                "@type": "/cosmos.bank.v1beta1.MsgSend",
                "from_address": gov_addr,
                "to_address": receiver,
                "amount": [{"denom": WMANTRAUSD_CONSUMER_IBC_DENOM, "amount": "1"}],
            }
        ],
    }
    proposal_file = tmp_path / "gov_arbitrary_msgsend_proposal.json"
    proposal_file.write_text(json.dumps(proposal))

    rsp = cli.submit_gov_proposal(
        proposal_file,
        from_="community",
        gas=400000,
        gas_prices=f"{CONSUMER_GAS_AMT}{WMANTRAUSD_CONSUMER_IBC_DENOM}",
    )
    assert rsp["code"] != 0, rsp
    assert "MsgSend" in rsp.get("raw_log", "")


def test_nvnmchaind_evm_coin_info_from_bank_metadata(ibc):
    consumer_cli = ibc.ibc2.cosmos_cli()
    base = consumer_cli.get_base_kwargs()

    params = json.loads(consumer_cli.raw("q", "evm", "params", **base))
    assert params["params"]["evm_denom"] == WMANTRAUSD_CONSUMER_IBC_DENOM

    match = consumer_cli.query_bank_denom_metadata(WMANTRAUSD_CONSUMER_IBC_DENOM)
    assert (
        match and match["base"] == WMANTRAUSD_CONSUMER_IBC_DENOM
    ), "miss bank denom_metadata entry for evm_denom"
    assert match["display"] == "wmantrausd"
    decimals = next(
        (u["exponent"] for u in match["denom_units"] if u["denom"] == match["display"]),
        None,
    )
    assert decimals == 18


async def test_ccv_rewards_buffer_rejects_user_bank_send(ibc):
    consumer_cli = ibc.ibc2.cosmos_cli()
    buffer_addr = module_address(
        "cons_to_send_to_provider",
        prefix="nvnm",
    )
    rsp = consumer_cli.transfer(
        consumer_cli.address("community"),
        buffer_addr,
        f"1{WMANTRAUSD_CONSUMER_IBC_DENOM}",
        gas_prices=f"{CONSUMER_GAS_AMT}{WMANTRAUSD_CONSUMER_IBC_DENOM}",
    )
    assert rsp["code"] != 0, rsp
    assert "restricted" in rsp["raw_log"], rsp


async def test_distribution_claim_precompile_rejects_user_bank_send(ibc):
    cli = ibc.ibc1.cosmos_cli()
    precompile_addr = eth_to_bech32(DISTRIBUTION_CLAIM_ADDRESS)
    rsp = cli.transfer(cli.address("community"), precompile_addr, f"1{DEFAULT_DENOM}")
    assert rsp["code"] != 0, rsp
    raw_log = rsp.get("raw_log", "").lower()
    assert "not allowed" in raw_log, rsp


async def test_precompile_rejects_cli_and_eth_value_transfer(ibc):
    consumer_cli = ibc.ibc2.cosmos_cli()
    w3 = ibc.ibc2.w3

    precompile_bech32 = eth_to_bech32(DOCUMENT_ADDRESS, prefix="nvnm")
    sender_bech32 = consumer_cli.address("community")

    rsp = consumer_cli.transfer(
        sender_bech32,
        precompile_bech32,
        f"1{WMANTRAUSD_CONSUMER_IBC_DENOM}",
        gas_prices=f"{CONSUMER_GAS_AMT}{WMANTRAUSD_CONSUMER_IBC_DENOM}",
    )
    assert rsp["code"] != 0, rsp
    assert "unauthorized" in rsp["raw_log"].lower(), rsp

    precompile_balance_bf = w3.eth.get_balance(DOCUMENT_ADDRESS)
    receipt = send_transaction(
        w3,
        {
            "from": ADDRS["community"],
            "to": DOCUMENT_ADDRESS,
            "value": 1,
            "gas": 100_000,
            **consumer_eip1559_fees(w3),
        },
        KEYS["community"],
    )
    assert receipt.status == 0
    assert w3.eth.get_balance(DOCUMENT_ADDRESS) == precompile_balance_bf


@pytest.mark.skip(reason="test_ccv_rewards_buffer_timeout_refund_path")
async def test_ccv_rewards_buffer_timeout_refund_path(ibc):
    consumer_cli = ibc.ibc2.cosmos_cli()
    buffer_addr = module_address(
        "cons_to_send_to_provider",
        prefix="nvnm",
    )

    buffer_bf = consumer_cli.balance(
        buffer_addr,
        denom=WMANTRAUSD_CONSUMER_IBC_DENOM,
    )

    ibc.ibc1.supervisorctl("stop", "relayer-demo")
    wait_for_new_blocks(consumer_cli, 2)

    sender = consumer_cli.address("community")
    for i in range(2):
        rsp = consumer_cli.transfer(
            sender,
            sender,
            f"1{WMANTRAUSD_CONSUMER_IBC_DENOM}",
            gas_prices=f"{CONSUMER_GAS_AMT}{WMANTRAUSD_CONSUMER_IBC_DENOM}",
        )
        assert rsp["code"] == 0, rsp["raw_log"]

    wait_for_new_blocks(consumer_cli, 15)

    ibc.ibc1.supervisorctl("start", "relayer-demo")

    def count_timeout_txs() -> int:
        queries = [
            "message.action='/ibc.core.channel.v1.MsgTimeout'",
            "message.action='/ibc.core.channel.v1.MsgTimeoutOnClose'",
            "message.action='/ibc.core.channel.v2.MsgTimeout'",
        ]
        tx_hashes = set()
        for query in queries:
            try:
                for tx in consumer_cli.tx_search_rpc(query):
                    tx_hash = tx.get("hash") or tx.get("txhash")
                    if tx_hash:
                        tx_hashes.add(tx_hash)
            except Exception:
                continue

        return len(tx_hashes)

    timeout_txs_bf = count_timeout_txs()

    wait_for_fn(
        "ccv timeout refund observed",
        lambda: count_timeout_txs() > timeout_txs_bf,
    )

    wait_for_new_blocks(consumer_cli, 2)

    rsp = consumer_cli.transfer(
        consumer_cli.address("community"),
        buffer_addr,
        f"1{WMANTRAUSD_CONSUMER_IBC_DENOM}",
        gas_prices=f"{CONSUMER_GAS_AMT}{WMANTRAUSD_CONSUMER_IBC_DENOM}",
    )
    assert rsp["code"] != 0, rsp

    buffer_af = consumer_cli.balance(
        buffer_addr,
        denom=WMANTRAUSD_CONSUMER_IBC_DENOM,
    )
    assert buffer_af >= buffer_bf


async def test_add_registry(ibc, setup_consumer_accounts):
    metadata = json.dumps(
        {
            "test": "ccv",
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
    )
    await do_test_add_registry(
        ibc.ibc2.async_w3,
        metadata=metadata,
    )


async def test_anchoring_static_precompile_state_override(ibc, setup_consumer_accounts):
    w3 = ibc.ibc2.async_w3

    registry_name = "state_override"
    await do_test_add_registry(
        w3,
        name=registry_name,
        metadata='{"source":"state_override"}',
    )

    registries_call = DOCUMENT_PRECOMPILE.fns.registries(
        0,
        registry_name,
        (b"", 0, 10, False, False),
    )
    tx = {
        "to": DOCUMENT_ADDRESS,
        "from": ADDRS["community"],
        "data": registries_call.data,
    }

    unrelated_address = "0x000000000000000000000000000000000000dEaD"
    empty_override = {unrelated_address: {}}
    unrelated_override = {
        unrelated_address: {
            "stateDiff": {
                "0x" + "0" * 64: "0x" + "01".zfill(64),
            }
        }
    }

    base = await w3.eth.call(tx, "latest")
    with_empty_override = await w3.eth.call(tx, "latest", empty_override)
    with_unrelated_override = await w3.eth.call(tx, "latest", unrelated_override)

    decoded_registries, _ = await registries_call.call(w3, to=DOCUMENT_ADDRESS)
    assert any(reg[1] == registry_name for reg in decoded_registries)

    assert len(base) > 0
    assert with_empty_override == base
    assert with_unrelated_override == base

    identity_tx = {
        "to": "0x0000000000000000000000000000000000000004",
        "from": ADDRS["community"],
        "data": registries_call.data,
    }
    identity_base = await w3.eth.call(identity_tx, "latest")
    identity_empty = await w3.eth.call(identity_tx, "latest", empty_override)
    identity_unrelated = await w3.eth.call(identity_tx, "latest", unrelated_override)
    expected_identity_output = bytes(registries_call.data)

    assert identity_base == expected_identity_output
    assert identity_base == identity_empty == identity_unrelated


async def test_anchoring_eth_estimate_gas_matches_eth_call(
    ibc, setup_consumer_accounts
):
    """Check eth_estimateGas matches receipt gas_used for anchoring precompile call."""
    w3 = ibc.ibc2.async_w3
    sender = get_accounts()["community"]

    block_number = await w3.eth.block_number
    registry_name = f"ccv-estimate-gas-regression-{block_number}"
    call = DOCUMENT_PRECOMPILE.fns.addRegistry(
        registry_name,
        "regression for eth_estimateGas under cosmos_evm native precompile",
        json.dumps(
            {
                "source": "ccv-estimate-gas-regression",
                "block": block_number,
            }
        ),
    )
    tx = {"to": DOCUMENT_ADDRESS, "from": sender.address, "data": call.data}

    # Estimate + floor check BEFORE broadcast — addRegistry writes state, so a
    # post-broadcast estimate would revert with "registry already exists".
    estimated = await assert_gas_estimate_within_floor(w3, tx)

    # Broadcast: consumer chain enforces a min_gas_price floor and transact()
    # doesn't auto-set EIP-1559 fees, so inject them via the sync w3 helper.
    fees = consumer_eip1559_fees(ibc.ibc2.w3)
    receipt = await call.transact(w3, sender, to=DOCUMENT_ADDRESS, gas=700_000, **fees)
    assert_estimate_covers_receipt(estimated, int(receipt["gasUsed"]))


async def test_erc20_precompile_state_override(ibc):
    """eth_call balanceOf on a native ERC20 precompile must return the same
    value under no override, empty `{}`, and an unrelated stateDiff override.
    """
    cli = ibc.ibc2.cosmos_cli()
    w3 = ibc.ibc2.async_w3
    denom = WMANTRAUSD_CONSUMER_IBC_DENOM
    holder = ADDRS["community"]
    pair_addr = ibc_denom_address(denom)

    pair = cli.query_erc20_token_pair(denom)
    if pair.get("contract_owner") != "OWNER_MODULE" or not pair.get("enabled"):
        pytest.skip(f"{denom} not registered as enabled OWNER_MODULE pair: {pair}")
    assert w3.to_checksum_address(pair["erc20_address"]) == pair_addr

    expected = cli.balance(cli.address("community"), denom=denom)
    assert expected > 0, "community need have balance"

    tx = {
        "to": pair_addr,
        "from": holder,
        "data": "0x"
        + (keccak(b"balanceOf(address)")[:4] + encode(["address"], [holder])).hex(),
    }

    base = await w3.eth.call(tx, "latest")
    (decoded,) = decode(["uint256"], bytes(base))
    assert decoded == expected, (decoded, expected)

    # Any non-nil override must not bypass the keeper-backed precompile.
    dead = "0x000000000000000000000000000000000000dEaD"
    for override in (
        {dead: {}},
        {dead: {"stateDiff": {"0x" + "0" * 64: "0x" + "01".zfill(64)}}},
    ):
        assert await w3.eth.call(tx, "latest", override) == base, override


async def test_anchoring_state_changing_methods_gas_delta_non_zero(
    ibc, setup_consumer_accounts
):
    async_w3 = ibc.ibc2.async_w3
    accounts = get_accounts()
    sender_account = accounts["community"]
    target = accounts["signer1"].address

    deltas = {}
    registry_name = "ccv-gas-methods"
    add_registry_call = DOCUMENT_PRECOMPILE.fns.addRegistry(
        registry_name,
        "ccv gas method matrix",
        json.dumps({"source": "ccv-gas-matrix", "kind": "registry"}),
    )
    add_registry_receipt, _ = await run_method(
        async_w3,
        sender_account,
        call=add_registry_call,
        gas=220_000,
        method="addRegistry",
        deltas=deltas,
    )

    registry_id = get_add_registry_event_registry_id(
        add_registry_receipt, caller=sender_account.address
    )
    assert registry_id > 0

    checksum = sha256_hex(f"ccv-gas-{registry_id}")
    record = Record(
        registry=registry_name,
        uri=f"ipfs://{checksum}",
        checksum=checksum,
        checksumAlgo="sha256",
        metadata=json.dumps({"document": "ccv-gas-matrix", "kind": "record"}),
        timestamp="",
        status="active",
        recordId=0,
        index=0,
        isLatest=False,
    )
    add_record_call = DOCUMENT_PRECOMPILE.fns.addRecord(astuple(record))
    await run_method(
        async_w3,
        sender_account,
        call=add_record_call,
        gas=700_000,
        method="addRecord",
        deltas=deltas,
    )

    records, _ = await DOCUMENT_PRECOMPILE.fns.records(
        registry_name,
        checksum,
        0,
        0,
        (b"", 0, 10, False, False),
    ).call(async_w3, to=DOCUMENT_ADDRESS)
    assert records, "expected record after addRecord"
    added = Record.from_tuple(records[0])

    update_status_call = DOCUMENT_PRECOMPILE.fns.updateRecordStatus(
        registry_id,
        added.recordId,
        added.index,
        "verified",
    )
    await run_method(
        async_w3,
        sender_account,
        call=update_status_call,
        gas=260_000,
        method="updateRecordStatus",
        deltas=deltas,
    )

    grant_role_call = DOCUMENT_PRECOMPILE.fns.grantRole(
        registry_id,
        "",
        target,
        "editor",
    )
    await run_method(
        async_w3,
        sender_account,
        call=grant_role_call,
        gas=260_000,
        method="grantRole",
        deltas=deltas,
    )

    revoke_role_call = DOCUMENT_PRECOMPILE.fns.revokeRole(
        registry_id,
        "",
        target,
        "editor",
    )
    await run_method(
        async_w3,
        sender_account,
        call=revoke_role_call,
        gas=260_000,
        method="revokeRole",
        deltas=deltas,
    )

    assert len(deltas) == 5
    assert all(delta > 0 for delta in deltas.values()), f"non-positive deltas: {deltas}"


async def test_anchoring_gas_delta_scales_with_metadata_size(
    ibc, setup_consumer_accounts
):
    async_w3 = ibc.ibc2.async_w3
    sender_account = get_accounts()["community"]
    metadata_sizes = [100, 1000]
    deltas = {}

    for size in metadata_sizes:
        call = DOCUMENT_PRECOMPILE.fns.addRegistry(
            f"ccv-gas-scale-{size}",
            "ccv gas delta scaling",
            "m" * size,
        )

        _, delta = await run_method(
            async_w3,
            sender_account,
            call=call,
            gas=300_000,
            method=f"addRegistry_metadata_{size}",
        )
        deltas[size] = delta

    assert deltas[1000] > deltas[100], "gas delta should scale with metadata size"


async def test_contract_cannot_call_anchoring_sensitive_methods(
    ibc, setup_consumer_accounts
):
    await do_test_contract_cannot_call_anchoring_sensitive_methods(ibc.ibc2.w3)


async def test_constructor_bypasses_ensure_eoa_caller_precompile_check(
    ibc, setup_consumer_accounts
):
    await do_test_constructor_bypass_ensure_eoa_caller(ibc.ibc2.w3)


@pytest.mark.parametrize("checksum", ["", sha256_hex("abc123def456")])
async def test_grant_and_revoke_role_as_admin(ibc, setup_consumer_accounts, checksum):
    await do_test_grant_and_revoke_role_as_admin(ibc.ibc2.async_w3, checksum)


async def test_disallow_last_admin_self_revoke(ibc, setup_consumer_accounts):
    await do_test_disallow_last_admin_self_revoke(ibc.ibc2.async_w3)


async def test_module_admin_emergency_admin_recovery(ibc, setup_consumer_accounts):
    await do_test_module_admin_emergency_admin_recovery(ibc.ibc2.async_w3)


async def test_add_record_rejects_oversized_checksum_algo(ibc, setup_consumer_accounts):
    w3 = ibc.ibc2.async_w3
    accounts = get_accounts()
    admin = accounts["community"]

    registry_name = "oversize-algo-registry"
    await do_test_add_registry(w3, name=registry_name, metadata="{}")

    oversized_algo = "a" * 129
    record = Record(
        registry=registry_name,
        uri="ipfs://oversize-algo",
        checksum=sha256_hex("abc123def456"),
        checksumAlgo=oversized_algo,
        metadata=json.dumps({"document": "oversize-algo"}),
        timestamp="",
        status="active",
        recordId=0,
        index=0,
        isLatest=False,
    )

    call = DOCUMENT_PRECOMPILE.fns.addRecord(astuple(record))
    with pytest.raises(Exception, match="checksum algorithm exceeds max length"):
        await w3.eth.call(
            {
                "to": DOCUMENT_ADDRESS,
                "from": admin.address,
                "data": call.data,
                "gas": 1_000_000,
            }
        )


@pytest.mark.parametrize("is_admin", [True, False])
async def test_grant_role_permissions(ibc, setup_consumer_accounts, is_admin):
    await do_test_grant_role_permissions(ibc.ibc2.async_w3, is_admin)


@pytest.mark.parametrize("is_admin", [True, False])
async def test_revoke_role_permissions(ibc, setup_consumer_accounts, is_admin):
    await do_test_revoke_role_permissions(ibc.ibc2.async_w3, is_admin)


@pytest.mark.parametrize(
    "name,method,build_case",
    [
        (
            "grant registry not found",
            "grant",
            lambda _w3, _accounts: {
                "registry_id": 999,
                "checksum": "",
                "account": _accounts["signer1"],
                "role": "editor",
                "sender": _accounts["community"],
                "expect_err": "registry 999 does not exist",
            },
        ),
        (
            "revoke registry zero with checksum",
            "revoke",
            lambda _w3, _accounts: {
                "registry_id": 0,
                "checksum": "any-checksum",
                "account": _accounts["signer1"],
                "role": "editor",
                "sender": _accounts["community"],
                "expect_err": "registry ID cannot be zero",
            },
        ),
    ],
)
async def test_role_scope_existence_validation(
    ibc, setup_consumer_accounts, name, method, build_case
):
    w3 = ibc.ibc2.async_w3
    accounts = get_accounts()
    case = build_case(w3, accounts)
    await do_test_role_scope_existence_validation(
        w3,
        method=method,
        registry_id=case["registry_id"],
        checksum=case["checksum"],
        account=case["account"],
        role=case["role"],
        sender=case["sender"],
        expect_err=case["expect_err"],
    )


async def test_revoke_record_checksum_missing_in_registry(ibc, setup_consumer_accounts):
    w3 = ibc.ibc2.async_w3
    accounts = get_accounts()
    registry_name = "ccv-role-scope"
    registry_id = await ensure_registry_exists(w3, registry_name, metadata="{}")
    await add_record(
        w3,
        accounts["community"],
        sha256_hex("present-checksum"),
        registry=registry_name,
    )
    err = f"record with checksum no-checksum does not exist in registry {registry_id}"
    await do_test_role_scope_existence_validation(
        w3,
        method="revoke",
        registry_id=registry_id,
        checksum="no-checksum",
        account=accounts["signer1"],
        role="editor",
        sender=accounts["community"],
        expect_err=err,
    )


async def test_multiple_roles_management(ibc, setup_consumer_accounts):
    await do_test_multiple_roles_management(ibc.ibc2.async_w3)


@pytest.mark.parametrize("role", [Role.EDITOR, Role.VIEWER])
async def test_role_idempotency(ibc, setup_consumer_accounts, role):
    await do_test_role_idempotency(ibc.ibc2.async_w3, role)


@pytest.mark.parametrize(
    "registry_role,record_role",
    [
        (Role.VIEWER, Role.EDITOR),
        (Role.EDITOR, Role.VIEWER),
    ],
)
async def test_record_level_overrides_registry_level(
    ibc, setup_consumer_accounts, registry_role, record_role
):
    await do_test_record_level_overrides_registry_level(
        ibc.ibc2.async_w3, registry_role, record_role
    )


@pytest.mark.parametrize(
    "doc1_role,doc2_role",
    [
        (Role.EDITOR, Role.VIEWER),
        (Role.VIEWER, Role.EDITOR),
        (Role.EDITOR, Role.EDITOR),
    ],
)
async def test_role_with_different_checksums(
    ibc, setup_consumer_accounts, doc1_role, doc2_role
):
    await do_test_role_with_different_checksums(ibc.ibc2.async_w3, doc1_role, doc2_role)


async def test_add_and_query_records(ibc, setup_consumer_accounts):
    await do_test_add_and_query_records(ibc.ibc2.async_w3)


async def test_add_record_same_checksum_maintains_record_id(
    ibc, setup_consumer_accounts
):
    await do_test_add_record_same_checksum_maintains_record_id(ibc.ibc2.async_w3)


async def test_add_record(ibc, setup_consumer_accounts):
    await do_test_add_record(ibc.ibc2.async_w3)


async def test_shared_checksum_in_multi_registries(ibc, setup_consumer_accounts):
    await do_test_shared_checksum_in_multi_registries(ibc.ibc2.async_w3)


async def test_query_by_registry_and_checksum(ibc, setup_consumer_accounts):
    await do_test_query_by_registry_and_checksum(ibc.ibc2.async_w3)


async def test_same_checksum_different_record_ids_per_registry(
    ibc, setup_consumer_accounts
):
    await do_test_same_checksum_different_record_ids_per_registry(ibc.ibc2.async_w3)


async def test_multiple_versions_same_checksum_across_registries(
    ibc, setup_consumer_accounts
):
    await do_test_multiple_versions_same_checksum_across_registries(ibc.ibc2.async_w3)


async def test_query_all_registries_for_checksum(ibc, setup_consumer_accounts):
    await do_test_query_all_registries_for_checksum(ibc.ibc2.async_w3)


async def test_checksum_only_query_respects_limit(ibc, setup_consumer_accounts):
    await do_test_checksum_only_query_respects_limit(ibc.ibc2.async_w3)


async def test_registry_only_query_respects_limit(ibc, setup_consumer_accounts):
    await do_test_registry_only_query_respects_limit(ibc.ibc2.async_w3)


def test_provider_bank_hooks_fire_on_reward_distribution(ibc):
    """
    Provider's SendCoinsFromModuleToModule must fire TokenFactory BeforeSend hooks.
    """
    provider_cli = ibc.ibc1.cosmos_cli()
    consumer_cli = ibc.ibc2.cosmos_cli()
    rpc = provider_cli.node_rpc_http

    # Resolve consumer_id from the provider (the fixture creates exactly one).
    rsp = json.loads(
        provider_cli.raw(
            "q",
            "provider",
            "list-consumer-chains",
            **provider_cli.get_base_kwargs(),
        )
    )
    consumer_id = next(
        c["consumer_id"]
        for c in rsp.get("chains") or []
        if c.get("chain_id") == "nvnm-canary-net-1"
    )

    validator = "validator"
    validator_addr = provider_cli.address(validator)
    gas = 2_500_000

    factory_denom = FACTORY_REWARD_DENOM
    factory_consumer_voucher = (
        f"ibc/{ibc_denom_hash(f'transfer/{TRANSFER_CHANNEL_ID}/{factory_denom}')}"
    )
    rsp = provider_cli.create_tokenfactory_denom(
        FACTORY_REWARD_SUBDENOM,
        _from=validator,
        gas=620_000,
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    rsp = provider_cli.mint_tokenfactory_denom(
        f"10000000000000{factory_denom}",
        _from=validator,
        gas=gas,
    )
    assert rsp["code"] == 0, rsp["raw_log"]

    # Upload + instantiate track_before_send listener and wire it.
    contract = Path(__file__).parent / "contracts/contracts/track_before_send.wasm"
    rsp = provider_cli.wasm_store(
        str(contract), validator_addr, _from=validator, gas=gas
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    store_attrs = find_log_event_attrs(
        rsp["events"],
        "store_code",
        lambda a: "code_id" in a,
    )
    assert store_attrs, "store_code event missing"
    code_id = store_attrs["code_id"]
    rsp = provider_cli.wasm_instantiate(
        code_id, validator_addr, _from=validator, gas=gas
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    inst_attrs = find_log_event_attrs(
        rsp["events"],
        "instantiate",
        lambda a: "_contract_address" in a,
    )
    assert inst_attrs, "instantiate event missing"
    listener_addr = inst_attrs["_contract_address"]
    rsp = provider_cli.set_tokenfactory_before_send_hook(
        factory_denom,
        listener_addr,
        _from=validator,
    )
    assert rsp["code"] == 0, rsp["raw_log"]

    # Bridge factory denom to consumer so its voucher exists there.
    rsp = provider_cli.ibc_transfer(
        consumer_cli.address("community"),
        f"1000000000000{factory_denom}",
        TRANSFER_CHANNEL_ID,
        _from=validator,
        gas=gas,
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    wait_for_new_blocks(consumer_cli, 5)
    assert (
        consumer_cli.balance(
            consumer_cli.address("community"),
            denom=factory_consumer_voucher,
        )
        > 0
    )

    # Mark observation window start.
    start_height = provider_cli.block_height()

    # IBC-deposit the factory voucher from consumer to provider's
    # ConsumerRewardsPool. Pay gas in the consumer's evm_denom (WMANTRAUSD
    # voucher); the consumer's MinGasPriceDecorator only accepts that.
    consumer_rewards_pool = module_address("consumer_rewards_pool", prefix="mantra")
    reward_memo = json.dumps(
        {
            "provider": {
                "consumerId": consumer_id,
                "chainId": "nvnm-canary-net-1",
                "memo": "ICS rewards",
            },
        }
    )
    rsp = consumer_cli.ibc_transfer(
        consumer_rewards_pool,
        f"100000000000{factory_consumer_voucher}",
        TRANSFER_CHANNEL_ID,
        _from="community",
        gas=500_000,
        gas_prices=f"{CONSUMER_GAS_AMT}{WMANTRAUSD_CONSUMER_IBC_DENOM}",
        note=reward_memo,
    )
    assert rsp["code"] == 0, rsp["raw_log"]

    # wait for IBC packet → allocation set → epoch end → AllocateTokens
    wait_for_new_blocks(provider_cli, 30, timeout=120)
    end_height = provider_cli.block_height()

    # Only the validators portion goes through Provider.bankKeeper (bug-sensitive);
    # the community portion goes through DistrKeeper (always-fires). Filter by
    # amount to detect the bug-sensitive listener fire.
    deposit = 100_000_000_000
    expected_min_validator_amount = deposit * 8 // 10

    listener_amounts = []
    for h in range(start_height + 1, end_height + 1):
        res = requests.get(f"{rpc}/block_results?height={h}").json().get("result") or {}
        candidates = (res.get("end_block_events") or []) + [
            ev
            for ev in (res.get("finalize_block_events") or [])
            if not any(a.get("key") == "txhash" for a in ev.get("attributes") or [])
        ]
        for ev in candidates:
            if ev.get("type") != "wasm":
                continue
            attrs = {a.get("key"): a.get("value") for a in ev.get("attributes") or []}
            if attrs.get("_contract_address") != listener_addr:
                continue
            amt = attrs.get("amount") or ""
            # amt "20000000factory/.../rewardhook"
            if amt.endswith(factory_denom):
                try:
                    listener_amounts.append((h, int(amt[: -len(factory_denom)])))
                except ValueError:
                    continue

    assert any(
        amount >= expected_min_validator_amount for _, amount in listener_amounts
    ), f"validator-portion listener fire missing; observed: {listener_amounts}"


def test_consumer_multisig(ibc, tmp_path):
    consumer_cli = ibc.ibc2.cosmos_cli()
    gas_prices = f"{CONSUMER_GAS_AMT}{WMANTRAUSD_CONSUMER_IBC_DENOM}"
    multisig_name = "multitest_anchor"
    gas_limit = 3_000_000
    fee_amt = int(CONSUMER_GAS_AMT) * gas_limit
    multi_addr = setup_multisig(
        consumer_cli,
        "community",
        "signer2",
        multisig_name,
        denom=WMANTRAUSD_CONSUMER_IBC_DENOM,
        gas_prices=gas_prices,
        fund_amt=fee_amt * 2,
    )

    registry_name = "multisig-whitepaper"
    checksum = sha256_hex("multisig-anchoring-payload")
    fee = f"{fee_amt}{WMANTRAUSD_CONSUMER_IBC_DENOM}"
    common = {
        "from_": multi_addr,
        "fees": fee,
        "gas": str(gas_limit),
        "chain_id": consumer_cli.chain_id,
        "keyring_backend": "test",
        "home": consumer_cli.data_dir,
        "node": consumer_cli.node_rpc,
        "output": "json",
    }
    add_registry_tx = json.loads(
        consumer_cli.raw(
            "tx",
            "anchoring",
            "add-registry",
            "--generate-only",
            name=registry_name,
            description="registry created via multisig",
            metadata='{"owner":"NVNM Foundation"}',
            **common,
        )
    )
    add_record_tx = json.loads(
        consumer_cli.raw(
            "tx",
            "anchoring",
            "add-record",
            "--generate-only",
            record=json.dumps(
                {
                    "registry": registry_name,
                    "uri": "ipfs://",
                    "checksum": checksum,
                    "checksum_algo": "sha256",
                    "metadata": '{"version":"1.0"}',
                    "status": "active",
                }
            ),
            **common,
        )
    )
    unsigned_tx = add_registry_tx
    unsigned_tx["body"]["messages"].extend(add_record_tx["body"]["messages"])

    multisig_sign_and_broadcast(
        consumer_cli,
        tmp_path,
        unsigned_tx,
        multisig_name,
        multi_addr,
        "community",
        "signer2",
    )

    registries = consumer_cli.raw(
        "q",
        "anchoring",
        "registries",
        node=consumer_cli.node_rpc,
        output="json",
    )
    assert registry_name in registries.decode("utf-8")

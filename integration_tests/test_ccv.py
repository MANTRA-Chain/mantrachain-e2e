import base64
import datetime
import json
import shutil
import time
from contextlib import contextmanager
from dataclasses import astuple
from pathlib import Path

import pytest
import requests
import tomlkit
from eth_account import Account
from eth_contract.contract import Contract
from eth_contract.create2 import create2_address
from eth_contract.deploy_utils import (
    ensure_create2_deployed,
    ensure_deployed_by_create2,
)
from eth_contract.erc20 import ERC20
from eth_contract.utils import get_initcode
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
    NAME_INDEX_PAGE,
    MatchMode,
    Role,
    add_record,
    assert_call_reverts,
    consumer_eip1559_fees,
    create_registry,
    deploy_anchoring_caller,
    ensure_registry_exists,
    find_document_event,
    get_registry_id,
    grant_role,
    new_record,
    query_records,
    record_metadata,
    registries_by_name,
    revoke_role,
    send_consumer_tx,
    send_document_call,
    sha256_hex,
    update_record_status,
)
from .ibc_utils import (
    IBCNetwork,
    create_channel,
    create_connection,
    ibc_denom_hash,
    ibc_timeout_ns,
)
from .network import Hermes, Mantra, setup_custom_mantra
from .utils import (
    ACCOUNTS,
    ADDRS,
    CMD,
    CONSUMER_GAS_AMT,
    DEFAULT_DENOM,
    KEYS,
    MockERC20_ARTIFACT,
    assert_estimate_covers_receipt,
    assert_gas_estimate_within_floor,
    build_contract,
    create_consumer_chain,
    eth_call_ignoring_overrides,
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

CONSUMER_CHAIN_ID = "nvnm-canary-net-1"
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


# Follow wmantraUSD's bytecode via its CREATE2 address, so a compiler change moves it:
# ibc/63C02A419B6F71F81AB7350335AB55D8A491D6926DFA91D1C8E226E1CABD419E
WMANTRAUSD_CONSUMER_IBC_DENOM = (
    f"ibc/{ibc_denom_hash(f'transfer/{TRANSFER_CHANNEL_ID}/{WMANTRAUSD_DENOM}')}"
)
# The consumer's fee floor, in its gas token, for CLI transactions.
CONSUMER_GAS_PRICES = f"{CONSUMER_GAS_AMT}{WMANTRAUSD_CONSUMER_IBC_DENOM}"

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
# Declared once so the selector, the return decode and the log decode all come
# from the same source instead of being restated per call site.
DISTRIBUTION_CLAIM = Contract.from_abi(
    [
        """
        function claimRewardsAndConvertCoin(
            address delegator, uint32 maxRetrieve, string memory denom
        ) returns (uint256 converted)
        """,
        """
        event ClaimRewardsAndConvertCoin(
            address indexed delegator, string denom, uint256 amount
        )
        """,
    ]
)


async def run_method(async_w3, sender_account, call, gas):
    "Transact `call`, returning the receipt and its gasUsed above intrinsic gas."
    receipt = await send_document_call(async_w3, call, sender_account, gas=gas)
    intrinsic = 21_000 + sum(4 if b == 0 else 16 for b in call.data)
    delta = int(receipt["gasUsed"]) - intrinsic
    assert delta > 0, f"gasUsed={receipt['gasUsed']} <= intrinsic={intrinsic}"
    return receipt, delta


@pytest.fixture(scope="module")
def ibc(request, tmp_path_factory):
    b_chain_cmd = "nvnmchaind"
    if shutil.which(b_chain_cmd) is None:
        pytest.skip(f"{b_chain_cmd} not enabled")
    chain = request.config.getoption("chain_config")
    name = "configs/ibc_nvnmchaind.jsonnet"
    path = tmp_path_factory.mktemp("ibc_nvnmchaind")
    b_chain = CONSUMER_CHAIN_ID
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
        owner_address = cli.address("validator")

        # consumer native denom (as `ibc/<hash>` on the provider)
        # bridge wmantraUSD rewards that unwrap back to `erc20:<addr>` on provider
        # FACTORY_REWARD_DENOM is included for the bank-hooks regression test;
        # adding it here avoids a second update_consumer_chain call (which would
        # be unauthorized once owner has been transferred to gov below).
        allowlisted_reward_denoms = [
            "ibc/"
            + ibc_denom_hash(
                f"transfer/{TRANSFER_CHANNEL_ID}/{WMANTRAUSD_CONSUMER_IBC_DENOM}"
            ),
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
        consumer_genesis["params"] |= {
            "reward_denoms": [WMANTRAUSD_CONSUMER_IBC_DENOM],
            # make rewards transmission frequent for faster rewards
            "blocks_per_distribution_transmission": "1",
            # keep reward transfer timeout short for timeout refund test
            "transfer_timeout_period": "10s",
        }
        now = datetime.datetime.now(datetime.UTC)

        for i in range(num_nodes):
            cons_node_dir = ibc2.base_dir / f"node{i}"
            prov_node_dir = ibc1.base_dir / f"node{i}"
            cons_cfg = cons_node_dir / "config"
            prov_cfg = prov_node_dir / "config"

            # genesis
            genesis_path = cons_cfg / "genesis.json"
            genesis = json.loads(genesis_path.read_text())
            genesis["genesis_time"] = now.isoformat().replace("+00:00", "Z")
            genesis["app_state"]["ccvconsumer"] = consumer_genesis
            genesis["app_state"]["feemarket"]["params"]["base_fee"] = "87600000000"
            genesis["app_state"]["feemarket"]["params"]["min_gas_price"] = "87600000000"
            genesis_path.write_text(json.dumps(genesis, indent=2))

            # priv val state
            state_path = cons_node_dir / "data" / "priv_validator_state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps({"height": "0", "round": 0, "step": 0}))

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
            doc = tomlkit.parse(config_path.read_text())
            doc["p2p"]["persistent_peers"] = peers
            config_path.write_text(tomlkit.dumps(doc))

            app_config_path = cons_cfg / "app.toml"
            app_doc = tomlkit.parse(app_config_path.read_text())
            # allow paying fees with bridged wmantraUSD IBC denom
            app_doc["minimum-gas-prices"] = f"0{WMANTRAUSD_CONSUMER_IBC_DENOM}"
            app_config_path.write_text(tomlkit.dumps(app_doc))

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
    receiver = ADDRS[signer]
    balance_bf = w3.eth.get_balance(receiver)
    amt = 1000
    receipt = send_consumer_tx(w3, {"to": receiver, "value": amt}, community)
    balance = w3.eth.get_balance(receiver)
    assert receipt.status == 1
    assert balance - balance_bf == amt
    amt = 2000
    denom = WMANTRAUSD_CONSUMER_IBC_DENOM
    rsp = cli2.transfer(
        cli2.address(community),
        cli2.address(signer),
        f"{amt}{denom}",
        gas_prices=CONSUMER_GAS_PRICES,
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    assert w3.eth.get_balance(receiver) - balance == amt


async def test_wmantrausd_bridge_deposit_to_consumer(ibc):
    provider_cli, consumer_cli = ibc.ibc1.cosmos_cli(), ibc.ibc2.cosmos_cli()

    wait_for_fn(
        "transfer channels open",
        lambda: all(
            check_channel_ready(cli, "transfer", TRANSFER_CHANNEL_ID)
            for cli in (consumer_cli, provider_cli)
        ),
        timeout=60,
    )

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
    wmantrausd_addr = PRED_WMANTRAUSD_ADDR
    wmantrausd = w3.eth.contract(address=wmantrausd_addr, abi=w_res["abi"])

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

    erc20_denom = WMANTRAUSD_DENOM
    ibc_denom = WMANTRAUSD_CONSUMER_IBC_DENOM

    amt_wmantrausd = amt_mantrausd * SCALAR
    expected = consumer_cli.balance(receiver_bech32, denom=ibc_denom) + amt_wmantrausd

    # 4) Ensure sender starts with 0 `erc20:<addr>` before MsgTransfer auto-converts.
    sender_bech32 = provider_cli.address(sender_name)
    assert provider_cli.balance(sender_bech32, denom=erc20_denom) == 0

    # 5) ICS20 transfer to consumer
    timeout_ns = ibc_timeout_ns()
    ics20_call = ICS20_PRECOMPILE.fns.transfer(
        "transfer",
        TRANSFER_CHANNEL_ID,
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

    ibc_logs = ICS20_PRECOMPILE.events.IBCTransfer.parse_logs(ics20_receipt["logs"])
    assert len(ibc_logs) == 1, f"expected 1 IBCTransfer event, got {len(ibc_logs)}"
    ev = ibc_logs[0].args
    assert ev.sender.lower() == sender.lower()
    assert ev.sourcePort == "transfer"
    assert ev.sourceChannel == TRANSFER_CHANNEL_ID
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
        TRANSFER_CHANNEL_ID,
        ibc_denom,
        return_amt_wmantrausd,
        receiver_evm,
        receiver_evm,
        (0, 0),
        timeout_ns,
        unwrap_memo,
    )
    ics20_return_receipt = send_consumer_tx(
        ibc.ibc2.w3,
        {"to": ICS20_ADDRESS, "data": ics20_return_call.data, "gas": 3_000_000},
        receiver_name,
    )
    assert ics20_return_receipt.status == 1

    # Consumer-side precompile emitted the return-leg IBCTransfer event.
    return_logs = ICS20_PRECOMPILE.events.IBCTransfer.parse_logs(
        ics20_return_receipt["logs"]
    )
    assert len(return_logs) == 1
    rev = return_logs[0].args
    assert rev.sender.lower() == receiver_evm.lower()
    assert rev.sourceChannel == TRANSFER_CHANNEL_ID
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
    claim_call = DISTRIBUTION_CLAIM.fns.claimRewardsAndConvertCoin(
        signer1_evm, max_retrieve, erc20_denom
    )

    # require(withdrawAddr == delegator)
    signer2 = provider_cli.address("signer2")
    rsp = provider_cli.set_withdraw_addr(signer2, from_=signer1, gas=200_000)
    assert rsp["code"] == 0, rsp["raw_log"]
    assert (
        provider_cli.distribution_withdraw_address(delegator_address=signer1) == signer2
    )

    claim_tx = {
        "to": DISTRIBUTION_CLAIM_ADDRESS,
        "data": claim_call.data,
        "gas": gas_limit,
    }
    bad_claim_convert_receipt = send_transaction(w3, claim_tx, KEYS["signer1"])
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
        return claim_call.decode(w3.eth.call({**claim_tx, "from": signer1_evm}))

    wait_for_fn(
        "expected_converted >= SCALAR",
        lambda: expected_converted_now() >= SCALAR,
    )

    bal_wmantrausd_bf = wmantrausd.functions.balanceOf(signer1_evm).call()
    bal_mantrausd_bf = mantrausd.functions.balanceOf(signer1_evm).call()

    # Claim+convert happens atomically in a single tx (all-or-nothing).
    # This checks we don't end up with a leftover `erc20:<addr>` bank coin.
    assert provider_cli.balance(signer1, denom=erc20_denom) == 0

    expected_converted = expected_converted_now()
    assert expected_converted > 0

    # claim + convert for the wmantraUSD token-pair denom
    receipt = send_transaction(w3, claim_tx, KEYS["signer1"])
    assert receipt.status == 1
    decoded = DISTRIBUTION_CLAIM.events.ClaimRewardsAndConvertCoin.parse_logs(
        [
            log
            for log in receipt["logs"]
            if log["address"].lower() == DISTRIBUTION_CLAIM_ADDRESS.lower()
        ]
    )
    assert len(decoded) == 1, receipt["logs"]

    args = decoded[0]["args"]
    assert args["delegator"].lower() == signer1_evm.lower()
    assert args["denom"] == erc20_denom
    ev_amount = args["amount"]
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
    assert provider_cli.balance(signer1, denom=erc20_denom) == 0

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
        gas_prices=CONSUMER_GAS_PRICES,
    )
    assert rsp["code"] != 0, rsp
    assert "MsgSend" in rsp.get("raw_log", "")


def test_nvnmchaind_evm_coin_info_from_bank_metadata(ibc):
    consumer_cli = ibc.ibc2.cosmos_cli()
    evm_denom = consumer_cli.get_params("evm")["evm_denom"]
    assert evm_denom == WMANTRAUSD_CONSUMER_IBC_DENOM

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
        gas_prices=CONSUMER_GAS_PRICES,
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
        gas_prices=CONSUMER_GAS_PRICES,
    )
    assert rsp["code"] != 0, rsp
    assert "unauthorized" in rsp["raw_log"].lower(), rsp

    precompile_balance_bf = w3.eth.get_balance(DOCUMENT_ADDRESS)
    receipt = send_consumer_tx(w3, {"to": DOCUMENT_ADDRESS, "value": 1, "gas": 100_000})
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
            gas_prices=CONSUMER_GAS_PRICES,
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
        gas_prices=CONSUMER_GAS_PRICES,
    )
    assert rsp["code"] != 0, rsp

    buffer_af = consumer_cli.balance(
        buffer_addr,
        denom=WMANTRAUSD_CONSUMER_IBC_DENOM,
    )
    assert buffer_af >= buffer_bf


async def test_add_registry(ibc):
    metadata = json.dumps(
        {
            "test": "ccv",
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
    )
    name = f"metadata-registry-{int(time.time() * 1000)}"
    await ensure_registry_exists(ibc.ibc2.async_w3, name, metadata=metadata)


async def test_registries_by_name(ibc):
    w3 = ibc.ibc2.async_w3
    api = ports.api_port(ibc.ibc2.base_port(0))
    search_url = (
        f"http://127.0.0.1:{api}/NVNM-Chain/nvnmchain/anchoring/v1/registries/search"
    )

    def rest(name, mode):
        params = {"name": name, "mode": int(mode)}  # TODO: by name after nvnmchain#49
        rsp = requests.get(search_url, params=params)
        assert rsp.ok, f"{rsp.status_code} {rsp.reason}: {rsp.text}"
        # uint64 comes back as a JSON string under the proto3 mapping
        return {int(r["id"]) for r in rsp.json().get("registries") or []}

    # Two registries differing only in case: the index lowercases at write time,
    # so either spelling returns both — and the result is multi-valued, which
    # names being non-unique demands.
    base = "ccv-name-index"
    mixed_id = await create_registry(w3, "CCV-Name-Index", metadata="{}")
    lower_id = await create_registry(w3, base, metadata="{}")
    tail_id = await create_registry(w3, f"{base}-tail", metadata="{}")
    both = {mixed_id, lower_id}
    all_three = both | {tail_id}

    for name, mode, expected in (
        # UNSPECIFIED is what a caller gets by leaving the field out; pin that
        # it behaves as EXACT rather than assuming it.
        (base, MatchMode.UNSPECIFIED, both),
        (base, MatchMode.EXACT, both),
        ("CCV-NAME-INDEX", MatchMode.EXACT, both),
        (f"{base}-tail", MatchMode.EXACT, {tail_id}),
        # Exact stays exact: no partial, no trimming.
        (f"{base}-nope", MatchMode.EXACT, set()),
        ("ccv-name", MatchMode.EXACT, set()),
        (f"{base} ", MatchMode.EXACT, set()),
        # Prefix/suffix/contains stay anchored, and all fold case.
        ("ccv-name", MatchMode.PREFIX, all_three),
        ("CCV-NAME", MatchMode.PREFIX, all_three),
        ("cv-name", MatchMode.PREFIX, set()),
        ("-tail", MatchMode.SUFFIX, {tail_id}),
        ("index", MatchMode.SUFFIX, both),
        ("-tai", MatchMode.SUFFIX, set()),
        ("name-index", MatchMode.CONTAINS, all_three),
        ("AME-IND", MatchMode.CONTAINS, all_three),
    ):
        assert await registries_by_name(w3, name, mode) == expected, (name, mode)
        # Both interfaces read the same index, so a divergence here means one
        # of them normalizes differently.
        assert rest(name, mode) == expected, (name, mode)

    # LIKE metacharacters are matched literally instead of turning the lookup
    # into a wildcard over every registry.
    hits = await registries_by_name(w3, f"{base[:3]}%", MatchMode.CONTAINS)
    assert not hits & all_three

    # CONTAINS is served from a trigram index, so it needs three characters;
    # shorter queries are refused on both interfaces rather than scanned.
    for short in ("%", "cc"):
        await assert_call_reverts(
            w3,
            sender=ADDRS["community"],
            data=DOCUMENT_PRECOMPILE.fns.registriesByName(
                short, int(MatchMode.CONTAINS), NAME_INDEX_PAGE
            ).data,
            expect_err="at least 3 characters",
        )
        rsp = requests.get(
            search_url, params={"name": short, "mode": int(MatchMode.CONTAINS)}
        )
        assert rsp.status_code == 400, f"{short!r}: {rsp.status_code} {rsp.text}"

    # An unknown mode is rejected rather than falling back to exact, which
    # would read as "no such registry".
    await assert_call_reverts(
        w3,
        sender=ADDRS["community"],
        data=DOCUMENT_PRECOMPILE.fns.registriesByName(base, 9, NAME_INDEX_PAGE).data,
        expect_err="invalid matchMode",
    )
    # TODO: 9 after nvnmchain#49
    rsp = requests.get(search_url, params={"name": base, "mode": "BOGUS"})
    assert rsp.status_code == 400, f"{rsp.status_code} {rsp.text}"

    # The plain registries listing is untouched by any of this.
    listing, _ = await DOCUMENT_PRECOMPILE.fns.registries(0, NAME_INDEX_PAGE).call(
        w3, to=DOCUMENT_ADDRESS
    )
    assert all_three <= {int(r[0]) for r in listing}


async def test_registries_by_name_pages_by_next_key(ibc):
    """Name search pages by `nextKey` like the registries list, and counts nothing."""
    w3 = ibc.ibc2.async_w3
    base = "ccv-paging"
    ids = [await create_registry(w3, f"{base}-{i}", metadata="{}") for i in range(3)]
    # The third id, in the registries list's key encoding.
    third = ids[2].to_bytes(8, "big")

    def search(key=b"", offset=0):
        page = (key, offset, 2, True, False)
        return DOCUMENT_PRECOMPILE.fns.registriesByName(
            base, int(MatchMode.PREFIX), page
        )

    # Two pages; the total stays 0 although countTotal is asked for.
    for key, rows, next_key in ((b"", ids[:2], third), (third, ids[2:], b"")):
        regs, (got_key, total) = await search(key).call(w3, to=DOCUMENT_ADDRESS)
        assert ([int(r[0]) for r in regs], got_key, total) == (rows, next_key, 0)

    for key, offset, err in (
        (third, 1, "either offset or key"),
        (b"\x01", 0, "invalid key"),
    ):
        await assert_call_reverts(
            w3, sender=ADDRS["community"], data=search(key, offset).data, expect_err=err
        )

    # The REST route returns the same keys in base64.
    api = ports.api_port(ibc.ibc2.base_port(0))
    url = f"http://127.0.0.1:{api}/NVNM-Chain/nvnmchain/anchoring/v1/registries/search"
    params = {"name": base, "mode": int(MatchMode.PREFIX), "pagination.limit": 2}
    for rows, next_key in ((ids[:2], third), (ids[2:], b"")):
        rsp = requests.get(url, params=params)
        assert rsp.ok, f"{rsp.status_code} {rsp.reason}: {rsp.text}"
        body = rsp.json()
        assert [int(r["id"]) for r in body["registries"]] == rows
        params["pagination.key"] = body["pagination"]["next_key"] or ""
        assert base64.b64decode(params["pagination.key"]) == next_key


async def test_registries_by_name_rejects_transaction(ibc):
    """Served as a call, refused as a transaction.

    The index is opt-in per node and may lag, so validators can disagree about
    the answer; letting it into block execution would make them disagree about
    the block. EOA-gating alone would not catch this — the sender here is an
    EOA calling the precompile directly.
    """
    async_w3, w3 = ibc.ibc2.async_w3, ibc.ibc2.w3
    # Shares no substring with the registries in test_registries_by_name, so
    # neither test depends on the order the two run in.
    name = "ccv-txgate-registry"
    registry_id = await create_registry(async_w3, name, metadata="{}")
    call = DOCUMENT_PRECOMPILE.fns.registriesByName(
        name, int(MatchMode.EXACT), NAME_INDEX_PAGE
    )

    assert await registries_by_name(async_w3, name, MatchMode.EXACT) == {registry_id}

    receipt = send_consumer_tx(
        w3, {"to": DOCUMENT_ADDRESS, "data": call.data, "gas": 1_000_000}
    )
    assert receipt.status == 0, "registriesByName must not succeed in a transaction"

    # The same input as a call at that block is served, so the refusal was the
    # gate and not a bad request. An eth_call always runs as a query, so the
    # revert reason is only observable from the transaction path; the unit
    # tests pin its text.
    regs, _ = await call.call(
        async_w3, to=DOCUMENT_ADDRESS, block_identifier=receipt.blockNumber
    )
    assert {int(r[0]) for r in regs} == {registry_id}


async def test_contract_cannot_call_registries_by_name(ibc):
    """Refused for a contract even though registriesByName is a view.

    Reads of consensus state stay open to contracts; this one does not, because
    its answer is node-local.
    """
    sender = ADDRS["community"]
    contract_addr, caller = await deploy_anchoring_caller(ibc.ibc2.w3, sender)
    # The name is immaterial: the call is refused before the index is read.
    call = caller.fns.callRegistriesByName("ccv-contract-caller", int(MatchMode.EXACT))
    await assert_call_reverts(
        ibc.ibc2.async_w3,
        sender=sender,
        to=contract_addr,
        data=call.data,
        expect_err="sender not an eoa",
        gas=1_000_000,
    )


async def test_anchoring_static_precompile_state_override(ibc):
    w3 = ibc.ibc2.async_w3

    registry_name = "state_override"
    registry_id = await ensure_registry_exists(
        w3,
        name=registry_name,
        metadata='{"source":"state_override"}',
    )

    registries_call = DOCUMENT_PRECOMPILE.fns.registries(
        registry_id,
        (b"", 0, 10, False, False),
    )
    tx = {
        "to": DOCUMENT_ADDRESS,
        "from": ADDRS["community"],
        "data": registries_call.data,
    }

    base = await eth_call_ignoring_overrides(w3, tx)
    assert len(base) > 0
    decoded_registries, _ = await registries_call.call(w3, to=DOCUMENT_ADDRESS)
    assert any(reg[1] == registry_name for reg in decoded_registries)

    identity_tx = {
        "to": "0x0000000000000000000000000000000000000004",
        "from": ADDRS["community"],
        "data": registries_call.data,
    }
    identity_base = await eth_call_ignoring_overrides(w3, identity_tx)
    assert identity_base == bytes(registries_call.data)


async def test_anchoring_eth_estimate_gas_matches_eth_call(ibc):
    """Check eth_estimateGas matches receipt gas_used for anchoring precompile call."""
    w3 = ibc.ibc2.async_w3
    sender = ACCOUNTS["community"]

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

    # Estimate against pre-broadcast state so it reflects this addRegistry's cost.
    estimated = await assert_gas_estimate_within_floor(w3, tx)

    # Broadcast: consumer chain enforces a min_gas_price floor and transact()
    # doesn't auto-set EIP-1559 fees, so inject them via the sync w3 helper.
    fees = consumer_eip1559_fees(ibc.ibc2.w3.eth.get_block("latest"))
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

    # Any non-nil override must not bypass the keeper-backed precompile.
    call = ERC20.fns.balanceOf(holder)
    tx = {"to": pair_addr, "from": holder, "data": call.data}
    decoded = call.decode(await eth_call_ignoring_overrides(w3, tx))
    assert decoded == expected, (decoded, expected)


async def test_anchoring_state_changing_methods_gas_delta_non_zero(ibc):
    async_w3 = ibc.ibc2.async_w3
    sender_account = ACCOUNTS["community"]
    target = ACCOUNTS["signer1"].address

    add_registry_call = DOCUMENT_PRECOMPILE.fns.addRegistry(
        "ccv-gas-methods",
        "ccv gas method matrix",
        json.dumps({"source": "ccv-gas-matrix", "kind": "registry"}),
    )
    add_registry_receipt, _ = await run_method(
        async_w3, sender_account, add_registry_call, 220_000
    )
    registry_id = int(
        find_document_event(
            add_registry_receipt, event="AddRegistry", caller=sender_account.address
        )["registryId"]
    )
    assert registry_id > 0

    checksum = sha256_hex(f"ccv-gas-{registry_id}")
    record = new_record(
        checksum,
        registry_id,
        metadata=json.dumps({"document": "ccv-gas-matrix", "kind": "record"}),
    )
    add_record_call = DOCUMENT_PRECOMPILE.fns.addRecord(astuple(record))
    await run_method(async_w3, sender_account, add_record_call, 700_000)

    records = await query_records(async_w3, registry_id, checksum, limit=10)
    assert records, "expected record after addRecord"
    added = records[0]

    fns = DOCUMENT_PRECOMPILE.fns
    for call in (
        fns.updateRecordStatus(registry_id, added.recordId, added.index, "verified"),
        fns.grantRole(registry_id, "", target, "editor"),
        fns.revokeRole(registry_id, "", target, "editor"),
    ):
        await run_method(async_w3, sender_account, call, 260_000)


async def test_anchoring_gas_delta_scales_with_metadata_size(ibc):
    async_w3 = ibc.ibc2.async_w3
    sender_account = ACCOUNTS["community"]
    metadata_sizes = [100, 1000]
    deltas = {}

    for size in metadata_sizes:
        call = DOCUMENT_PRECOMPILE.fns.addRegistry(
            f"ccv-gas-scale-{size}",
            "ccv gas delta scaling",
            "m" * size,
        )

        _, deltas[size] = await run_method(async_w3, sender_account, call, 300_000)

    assert deltas[1000] > deltas[100], "gas delta should scale with metadata size"


async def test_contract_cannot_call_anchoring_sensitive_methods(ibc):
    w3, async_w3 = ibc.ibc2.w3, ibc.ibc2.async_w3
    sender = ADDRS["community"]
    contract_addr, caller = await deploy_anchoring_caller(w3, sender)

    async def assert_reverted(call):
        await assert_call_reverts(
            async_w3,
            sender=sender,
            to=contract_addr,
            data=call.data,
            expect_err="sender not an eoa",
            gas=1_000_000,
        )

    await assert_reverted(
        caller.fns.callAddRegistry(
            "ccv-contract-caller-registry", "repro non-EOA guard", "{}"
        )
    )

    eoa_add_registry_call = DOCUMENT_PRECOMPILE.fns.addRegistry(
        "ccv-eoa-registry",
        "repro EOA guard",
        "{}",
    )
    eoa_add_registry_receipt = send_consumer_tx(
        w3,
        {"to": DOCUMENT_ADDRESS, "data": eoa_add_registry_call.data, "gas": 1_000_000},
    )
    assert eoa_add_registry_receipt.status == 1
    registry_id = int(
        find_document_event(
            eoa_add_registry_receipt, event="AddRegistry", caller=sender
        )["registryId"]
    )

    record = new_record(
        sha256_hex("ccv-contract-caller-checksum"),
        registry_id,
        metadata="{}",
        uri="ipfs://ccv-contract-caller",
    )
    await assert_reverted(caller.fns.callAddRecord(astuple(record)))
    await assert_reverted(
        caller.fns.callUpdateRecordStatus(registry_id, 1, 1, "verified")
    )
    for fn in (caller.fns.callGrantRole, caller.fns.callRevokeRole):
        await assert_reverted(fn(registry_id, "", ADDRS["signer1"], Role.EDITOR.value))


async def test_constructor_bypasses_ensure_eoa_caller_precompile_check(ibc):
    w3 = ibc.ibc2.w3
    sender = ADDRS["community"]
    artifact = build_contract("AnchoringConstructorCaller")
    contract = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])

    registry_name = f"ccv-constructor-bypass-{int(time.time() * 1000)}"
    deploy_tx = contract.constructor(registry_name).build_transaction(
        {
            "from": sender,
            "gas": 2_000_000,
            **consumer_eip1559_fees(w3.eth.get_block("latest")),
        }
    )
    deploy_receipt = send_transaction(w3, deploy_tx, KEYS["community"])
    assert deploy_receipt.status == 1

    deployed = w3.eth.contract(
        address=deploy_receipt.contractAddress, abi=artifact["abi"]
    )
    registry_created = deployed.functions.registryCreated().call()
    created_registry_id = int(deployed.functions.createdRegistryId().call())

    assert not registry_created, "constructor call should not bypass ensureEOACaller"
    assert (
        created_registry_id == 0
    ), "expected no registry created from constructor call"


@pytest.mark.parametrize("checksum", ["", sha256_hex("abc123def456")])
async def test_grant_and_revoke_role_as_admin(ibc, checksum):
    w3 = ibc.ibc2.async_w3
    registry_id = await ensure_registry_exists(w3)
    admin = ACCOUNTS["community"]
    editor = ACCOUNTS["signer1"]

    if checksum:
        await add_record(w3, admin, checksum)

    await grant_role(w3, registry_id, checksum, editor, Role.EDITOR, admin)
    await revoke_role(w3, registry_id, checksum, editor, Role.EDITOR, admin)


async def test_disallow_last_admin_self_revoke(ibc):
    w3 = ibc.ibc2.async_w3
    registry_name = f"lockout-registry-{int(time.time() * 1000)}"
    registry_id = await ensure_registry_exists(w3, registry_name, metadata="{}")

    admin = ACCOUNTS["community"]
    replacement_admin = ACCOUNTS["validator"]
    target = ACCOUNTS["signer2"]

    # last-admin revoke must fail
    call = DOCUMENT_PRECOMPILE.fns.revokeRole(
        registry_id,
        "",
        admin.address,
        "admin",
    )
    await assert_call_reverts(
        w3,
        sender=admin.address,
        data=call.data,
    )

    # revocation should succeed after adding a replacement admin
    await grant_role(w3, registry_id, "", replacement_admin, "admin", admin)

    await revoke_role(w3, registry_id, "", admin, "admin", admin)

    # replacement admin can still perform admin actions
    await grant_role(w3, registry_id, "", target, Role.EDITOR, replacement_admin)


async def test_module_admin_emergency_admin_recovery(ibc):
    w3 = ibc.ibc2.async_w3
    registry_name = f"breakglass-registry-{int(time.time() * 1000)}"

    module_admin = ACCOUNTS["reserve"]
    registry_admin = ACCOUNTS["validator"]
    replacement_admin = ACCOUNTS["signer2"]
    target = ACCOUNTS["community"]

    call = DOCUMENT_PRECOMPILE.fns.addRegistry(
        registry_name,
        registry_name,
        "{}",
    )
    await send_document_call(
        w3, call, registry_admin, f"failed to create registry {registry_name}"
    )

    registry_id = await get_registry_id(w3, registry_name)

    # module admin cannot orphan the registry by revoking the sole admin directly
    # that would leave zero admins. Recovery must go grant-first, then revoke
    revoke_sole_call = DOCUMENT_PRECOMPILE.fns.revokeRole(
        registry_id, "", registry_admin.address, "admin"
    )
    await assert_call_reverts(
        w3,
        sender=module_admin.address,
        data=revoke_sole_call.data,
        expect_err="cannot revoke the last registry admin",
    )

    # break-glass: module admin grants a replacement admin 1st (registry never orphaned)
    await grant_role(w3, registry_id, "", replacement_admin, "admin", module_admin)

    # the replacement admin — which now holds the registry admin role — revokes
    # the original admin. module_admin was never granted admin on this registry,
    # so the revoke must come from the replacement.
    await revoke_role(w3, registry_id, "", registry_admin, "admin", replacement_admin)

    # removed registry admin should no longer be able to perform admin actions
    grant_editor_call = DOCUMENT_PRECOMPILE.fns.grantRole(
        registry_id, "", target.address, Role.EDITOR
    )
    await assert_call_reverts(
        w3,
        sender=registry_admin.address,
        data=grant_editor_call.data,
    )

    # recovered admin can perform admin actions
    await grant_role(w3, registry_id, "", target, Role.EDITOR, replacement_admin)


async def test_add_record_rejects_oversized_checksum_algo(ibc):
    w3 = ibc.ibc2.async_w3
    admin = ACCOUNTS["community"]

    registry_name = "oversize-algo-registry"
    registry_id = await ensure_registry_exists(w3, name=registry_name, metadata="{}")

    record = new_record(
        sha256_hex("abc123def456"),
        registry_id,
        metadata=json.dumps({"document": "oversize-algo"}),
        uri="ipfs://oversize-algo",
        checksum_algo="a" * 129,
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


@pytest.mark.parametrize("method", ["grant", "revoke"])
@pytest.mark.parametrize("is_admin", [True, False])
async def test_role_changes_need_registry_admin(ibc, method, is_admin):
    w3 = ibc.ibc2.async_w3
    registry_id = await ensure_registry_exists(w3)
    admin, editor = ACCOUNTS["community"], ACCOUNTS["signer1"]
    sender = admin if is_admin else ACCOUNTS["signer2"]
    if method == "revoke":
        await grant_role(w3, registry_id, "", editor, Role.EDITOR, admin)

    if is_admin:
        change = grant_role if method == "grant" else revoke_role
        await change(w3, registry_id, "", editor, Role.EDITOR, sender)
    else:
        call = getattr(DOCUMENT_PRECOMPILE.fns, f"{method}Role")(
            registry_id, "", editor.address, Role.EDITOR
        )
        await assert_call_reverts(w3, sender=sender.address, data=call.data)


@pytest.mark.parametrize(
    "method,registry_id,checksum,expect_err",
    [
        pytest.param(
            "grant",
            999,
            "",
            "registry 999 does not exist",
            id="grant-registry-not-found",
        ),
        pytest.param(
            "revoke",
            0,
            "any-checksum",
            "registry ID cannot be zero",
            id="revoke-registry-zero-with-checksum",
        ),
    ],
)
async def test_role_scope_existence_validation(
    ibc, method, registry_id, checksum, expect_err
):
    fn = getattr(DOCUMENT_PRECOMPILE.fns, f"{method}Role")
    await assert_call_reverts(
        ibc.ibc2.async_w3,
        sender=ADDRS["community"],
        data=fn(registry_id, checksum, ADDRS["signer1"], "editor").data,
        expect_err=expect_err,
    )


async def test_revoke_record_checksum_missing_in_registry(ibc):
    w3 = ibc.ibc2.async_w3
    registry_name = "ccv-role-scope"
    registry_id = await ensure_registry_exists(w3, registry_name, metadata="{}")
    await add_record(
        w3,
        ACCOUNTS["community"],
        sha256_hex("present-checksum"),
        registry=registry_name,
    )
    call = DOCUMENT_PRECOMPILE.fns.revokeRole(
        registry_id, "no-checksum", ADDRS["signer1"], "editor"
    )
    await assert_call_reverts(
        w3,
        sender=ADDRS["community"],
        data=call.data,
        expect_err="record with checksum no-checksum does not exist "
        f"in registry {registry_id}",
    )


async def test_multiple_roles_management(ibc):
    w3 = ibc.ibc2.async_w3
    registry_id = await ensure_registry_exists(w3)
    admin = ACCOUNTS["community"]
    users_and_roles = [
        (ACCOUNTS["signer1"], Role.EDITOR),
        (ACCOUNTS["signer2"], Role.EDITOR),
        (ACCOUNTS["validator"], Role.VIEWER),
    ]
    for user, role in users_and_roles:
        await grant_role(w3, registry_id, "", user, role, admin)
    for user, role in users_and_roles:
        await revoke_role(w3, registry_id, "", user, role, admin)


@pytest.mark.parametrize("role", [Role.EDITOR, Role.VIEWER])
async def test_role_idempotency(ibc, role):
    w3 = ibc.ibc2.async_w3
    registry_id = await ensure_registry_exists(w3)
    admin = ACCOUNTS["community"]
    editor = ACCOUNTS["signer1"]
    checksum = ""

    await grant_role(w3, registry_id, checksum, editor, role, admin)
    # second grant should be idempotent
    await grant_role(w3, registry_id, checksum, editor, role, admin)


@pytest.mark.parametrize(
    "registry_role,record_role",
    [
        (Role.VIEWER, Role.EDITOR),
        (Role.EDITOR, Role.VIEWER),
    ],
)
async def test_record_level_overrides_registry_level(ibc, registry_role, record_role):
    w3 = ibc.ibc2.async_w3
    registry_id = await ensure_registry_exists(w3)
    admin = ACCOUNTS["community"]
    user = ACCOUNTS["signer1"]
    reg_checksum = ""
    doc_checksum = sha256_hex("doc123")

    await add_record(w3, admin, doc_checksum)

    # registry-level role
    await grant_role(w3, registry_id, reg_checksum, user, registry_role, admin)
    # record-level role (should override)
    await grant_role(w3, registry_id, doc_checksum, user, record_role, admin)
    # cleanup
    await revoke_role(w3, registry_id, reg_checksum, user, registry_role, admin)
    await revoke_role(w3, registry_id, doc_checksum, user, record_role, admin)


@pytest.mark.parametrize(
    "doc1_role,doc2_role",
    [
        (Role.EDITOR, Role.VIEWER),
        (Role.VIEWER, Role.EDITOR),
        (Role.EDITOR, Role.EDITOR),
    ],
)
async def test_role_with_different_checksums(ibc, doc1_role, doc2_role):
    w3 = ibc.ibc2.async_w3
    registry_id = await ensure_registry_exists(w3)
    admin = ACCOUNTS["community"]
    user = ACCOUNTS["signer1"]
    doc1_checksum = sha256_hex("doc1")
    doc2_checksum = sha256_hex("doc2")

    await add_record(w3, admin, doc1_checksum)
    await add_record(w3, admin, doc2_checksum)

    await grant_role(w3, registry_id, doc1_checksum, user, doc1_role, admin)
    await grant_role(w3, registry_id, doc2_checksum, user, doc2_role, admin)

    await revoke_role(w3, registry_id, doc1_checksum, user, doc1_role, admin)
    await revoke_role(w3, registry_id, doc2_checksum, user, doc2_role, admin)


async def test_add_and_query_records(ibc):
    w3 = ibc.ibc2.async_w3
    registry_name = f"query-registry-{int(time.time() * 1000)}"
    registry_id = await ensure_registry_exists(w3, name=registry_name)
    admin = ACCOUNTS["community"]

    for checksum, name in [
        (sha256_hex("abc123"), "Record 1"),
        (sha256_hex("abc123"), "Record 1 v2"),
        (sha256_hex("def456"), "Record 2"),
    ]:
        await add_record(w3, admin, checksum, name=name, registry=registry_name)

    # The second abc123 is a new version of the same record, not a new record.
    docs = await query_records(w3, registry_id, limit=10, count_total=True)
    assert len(docs) == 2, f"Expected 2 unique records, got {len(docs)}"

    abc_doc = next((d for d in docs if d.checksum == sha256_hex("abc123")), None)
    assert abc_doc is not None
    assert abc_doc.index == 2
    assert json.loads(abc_doc.metadata)["document"] == "Record 1 v2"


async def test_add_record(ibc):
    w3 = ibc.ibc2.async_w3
    admin = ACCOUNTS["community"]
    registry_id = await ensure_registry_exists(w3)
    for checksum, name, status in [
        (sha256_hex("record_123"), "Test Record", "verified"),
        (sha256_hex("remove_test_123"), "To Remove", "removed"),
    ]:
        receipt = await add_record(w3, admin, checksum, name=name)
        args = find_document_event(receipt, event="AddRecord", caller=admin.address)
        records = await query_records(w3, registry_id, record_id=args["recordId"])
        assert len(records) == 1, f"expected 1 record, got {len(records)}"
        record = records[0]
        assert record.checksum == checksum

        await update_record_status(w3, admin, record, status)


async def test_shared_checksum_in_multi_registries(ibc):
    w3 = ibc.ibc2.async_w3
    admin = ACCOUNTS["community"]
    checksum = sha256_hex("shared_checksum_abc123")
    expected = []
    # multi3 holds no record of the checksum, so a query by it must leave it out.
    for name, document in (("multi1", "doc1"), ("multi2", "doc2"), ("multi3", None)):
        registry_id = await ensure_registry_exists(w3, name=name)
        if document:
            await add_record(
                w3, admin, checksum, registry=name, metadata=record_metadata(document)
            )
            expected.append((registry_id, document))
    records = await query_records(w3, checksum=checksum)
    got = [(r.registryId, json.loads(r.metadata)["document"]) for r in records]
    assert sorted(got) == sorted(expected)


async def test_query_by_registry_and_checksum(ibc):
    w3 = ibc.ibc2.async_w3
    admin = ACCOUNTS["community"]
    registry_name = "query-specific-reg"
    registry_id = await ensure_registry_exists(w3, name=registry_name)

    registries, _ = await DOCUMENT_PRECOMPILE.fns.registries(
        registry_id, (b"", 0, 10, False, False)
    ).call(w3, to=DOCUMENT_ADDRESS)
    assert registries

    checksum = sha256_hex("query_test_checksum")
    await add_record(
        w3, admin, checksum, name="Query Test Record", registry=registry_name
    )
    records = await query_records(w3, registry_id, checksum)

    assert len(records) == 1
    rec = records[0]
    assert rec.checksum == checksum
    assert rec.registryId == registry_id


async def test_same_checksum_keeps_one_record_per_registry(ibc):
    w3 = ibc.ibc2.async_w3
    admin = ACCOUNTS["community"]
    registries = ["version-test-1", "version-test-2"]
    checksum = sha256_hex("multi_version_checksum")
    for name in registries:
        await ensure_registry_exists(w3, name=name)

    # Each registry keeps its own record; each new version raises its index.
    for index, version in enumerate(["v1.0", "v2.0"], start=1):
        for name in registries:
            await add_record(w3, admin, checksum, name=version, registry=name)
        records = await query_records(w3, checksum=checksum)
        got = [
            (r.index, r.isLatest, json.loads(r.metadata)["document"]) for r in records
        ]
        assert got == [(index, True, version)] * len(registries)


async def test_checksum_only_query_respects_limit(ibc):
    w3 = ibc.ibc2.async_w3
    admin = ACCOUNTS["community"]

    checksum = sha256_hex("checksum_limit_test")
    registries = ["checksum-limit-a", "checksum-limit-b", "checksum-limit-c"]

    for name in registries:
        await ensure_registry_exists(w3, name=name)
        await add_record(w3, admin, checksum, name=f"record in {name}", registry=name)

    # explicit limit/offset should work.
    page1 = await query_records(w3, checksum=checksum, limit=1)
    page2 = await query_records(w3, checksum=checksum, offset=1, limit=1)
    assert len(page1) == 1
    assert len(page2) == 1
    assert {r.registryId for r in page1}.isdisjoint({r.registryId for r in page2})


async def test_registry_only_query_respects_limit(ibc):
    w3 = ibc.ibc2.async_w3
    admin = ACCOUNTS["community"]

    reg_a = "reg-limit-a"
    reg_b = "reg-limit-b"

    await ensure_registry_exists(w3, name=reg_a)
    registry_id_b = await ensure_registry_exists(w3, name=reg_b)

    # add records under A first
    for i in range(5):
        await add_record(
            w3,
            admin,
            checksum=sha256_hex(f"checksum-a-{i}"),
            name=f"record a {i}",
            registry=reg_a,
        )

    checksum_b = sha256_hex("checksum-b")
    await add_record(
        w3,
        admin,
        checksum=checksum_b,
        name="record b",
        registry=reg_b,
    )

    page = await query_records(w3, registry_id_b, limit=1)
    assert len(page) == 1
    assert page[0].registryId == registry_id_b
    assert page[0].checksum == checksum_b


def test_provider_bank_hooks_fire_on_reward_distribution(ibc):
    """
    Provider's SendCoinsFromModuleToModule must fire TokenFactory BeforeSend hooks.
    """
    provider_cli = ibc.ibc1.cosmos_cli()
    consumer_cli = ibc.ibc2.cosmos_cli()
    rpc = provider_cli.node_rpc_http

    # Resolve consumer_id from the provider (the fixture creates exactly one).
    rsp = provider_cli._query("provider", "list-consumer-chains")
    consumer_id = next(
        c["consumer_id"]
        for c in rsp.get("chains") or []
        if c.get("chain_id") == CONSUMER_CHAIN_ID
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
                "chainId": CONSUMER_CHAIN_ID,
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
        gas_prices=CONSUMER_GAS_PRICES,
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
    multisig_name = "multitest_anchor"
    gas_limit = 3_000_000
    fee_amt = int(CONSUMER_GAS_AMT) * gas_limit
    multi_addr = setup_multisig(
        consumer_cli,
        "community",
        "signer2",
        multisig_name,
        denom=WMANTRAUSD_CONSUMER_IBC_DENOM,
        gas_prices=CONSUMER_GAS_PRICES,
        fund_amt=fee_amt * 2,
    )

    registry_name = "multisig-whitepaper"
    checksum = sha256_hex("multisig-anchoring-payload")
    fee = f"{fee_amt}{WMANTRAUSD_CONSUMER_IBC_DENOM}"
    common = consumer_cli.get_kwargs() | {
        "from_": multi_addr,
        "fees": fee,
        "gas": str(gas_limit),
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
    # Records reference their registry by id. The add-registry above is message[0] of
    # this tx, so the new registry gets the next id: current highest + 1 (ids are
    # sequential and never reused). --page-count-total is rejected, so read the highest
    # id via a reverse page of one.
    highest = consumer_cli._query(
        "anchoring", "registries", page_reverse=True, page_limit=1
    )
    existing = highest["registries"]
    next_registry_id = (int(existing[0]["id"]) if existing else 0) + 1
    add_record_tx = json.loads(
        consumer_cli.raw(
            "tx",
            "anchoring",
            "add-record",
            "--generate-only",
            record=json.dumps(
                {
                    "registry_id": next_registry_id,
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

    # Query the just-created registry by id (pagination-proof) and check its name.
    created = consumer_cli._query(
        "anchoring", "registries", registry_id=next_registry_id
    )
    names = [r["name"] for r in created["registries"]]
    assert registry_name in names, names

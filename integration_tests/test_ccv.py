import datetime
import json
import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest
import tomlkit
from eth_abi import decode, encode
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
    parse_amount,
    parse_denom,
    wait_for_fn,
    wait_for_new_blocks,
    wait_for_port,
)

from .doc_utils import (
    Role,
    clear_accounts_override,
    do_test_add_and_query_records,
    do_test_add_record,
    do_test_add_record_same_checksum_maintains_record_id,
    do_test_add_registry,
    do_test_grant_and_revoke_role_as_admin,
    do_test_grant_role_permissions,
    do_test_multiple_roles_management,
    do_test_multiple_versions_same_checksum_across_registries,
    do_test_query_all_registries_for_checksum,
    do_test_query_by_registry_and_checksum,
    do_test_record_level_overrides_registry_level,
    do_test_remove_record,
    do_test_revoke_role_permissions,
    do_test_role_idempotency,
    do_test_role_with_different_checksums,
    do_test_same_checksum_different_record_ids_per_registry,
    do_test_shared_checksum_in_multi_registries,
    set_accounts_override,
)
from .ibc_utils import IBCNetwork, create_channel, create_connection, ibc_denom_hash
from .network import Hermes, Mantra, setup_custom_mantra
from .utils import (
    ADDRS,
    CMD,
    DEFAULT_DENOM,
    DEFAULT_GAS_AMT,
    KEYS,
    MNEMONICS,
    MockERC20_ARTIFACT,
    build_contract,
    create_consumer_chain,
    send_transaction,
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


# ibc/343425D4475D42FD371D0A9CD2BC314F9E3238D59B9BEA0A747D4D1AFBBC7CC9
WMANTRAUSD_CONSUMER_IBC_DENOM = wmantrausd_consumer_ibc_denom(TRANSFER_CHANNEL_ID)
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
    b_chain_cmd = "inveniamd"
    if shutil.which(b_chain_cmd) is None:
        pytest.skip(f"{b_chain_cmd} not enabled")
    chain = request.config.getoption("chain_config")
    name = "configs/ibc_inveniamd.jsonnet"
    path = tmp_path_factory.mktemp("ibc_inveniamd")
    b_chain = "inveniam-canary-net-1"
    with contextmanager(setup_custom_mantra)(
        path,
        27400,
        Path(__file__).parent / name,
        relayer=cluster.Relayer.HERMES.value,
        chain=chain,
        chain_binary=f"{b_chain_cmd},{CMD}",
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

        authority = cli.get_params("marketmap").get("admin")
        port = "transfer"
        channel = TRANSFER_CHANNEL_ID
        denom = WMANTRAUSD_CONSUMER_IBC_DENOM
        denom_hash = ibc_denom_hash(f"{port}/{channel}/{denom}")
        owner_address = cli.address("validator")

        # consumer native denom (as `ibc/<hash>` on the provider)
        # bridge wmantraUSD rewards that unwrap back to `erc20:<wmantraUSD>` on provider
        allowlisted_reward_denoms = [
            f"ibc/{denom_hash}",
            WMANTRAUSD_DENOM,
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
            genesis["app_state"]["feemarket"]["params"]["base_fee"] = "10000000000"
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
        gas_prices=f"{DEFAULT_GAS_AMT}{denom}",
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
    assert consumer_transfer_channel and provider_transfer_channel

    # channel-0 is for CCV and TRANSFER_CHANNEL_ID is the ICS20 transfer channel
    assert consumer_transfer_channel == TRANSFER_CHANNEL_ID
    assert provider_transfer_channel == TRANSFER_CHANNEL_ID

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
        wmantrausd.functions.deposit(amt_mantrausd).build_transaction(
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

    # 4) Ensure sender start with 0 erc20:<wmantraUSD> before MsgTransfer auto-converts
    sender_bech32 = provider_cli.address(sender_name)
    assert provider_cli.balance(sender_bech32, denom=erc20_denom) == 0

    # 5) ICS20 transfer
    timeout_ns = int(
        (
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10)
        ).timestamp()
        * 1_000_000_000
    )
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
    ics20_receipt = send_transaction(
        w3,
        {
            "to": ICS20_ADDRESS,
            "data": ics20_call.data,
            "gas": 3_000_000,
        },
        sender_key,
    )
    assert ics20_receipt.status == 1

    def received() -> bool:
        return consumer_cli.balance(receiver_bech32, denom=ibc_denom) >= expected

    wait_for_fn("wmantraUSD bridged balance", received, timeout=60)
    assert consumer_cli.balance(receiver_bech32, denom=ibc_denom) == expected

    # 5b) Reverse flow: send `ibc/<hash>` back to provider.
    # Provider transfer middleware auto-converts returned `erc20:<addr>` bank coins
    # into their ERC20 form (convert-coin) when the receiver is an EVM hex address.
    receiver_evm = ADDRS[receiver_name]
    return_amt_wmantrausd = 10**15
    assert (
        consumer_cli.balance(receiver_bech32, denom=ibc_denom) > return_amt_wmantrausd
    )

    provider_wmantrausd_bal_bf = wmantrausd.functions.balanceOf(receiver_evm).call()
    consumer_ibc_bal_bf = consumer_cli.balance(receiver_bech32, denom=ibc_denom)

    return_rsp = consumer_cli.ibc_transfer(
        receiver_evm,
        f"{return_amt_wmantrausd}{ibc_denom}",
        consumer_transfer_channel,
        from_=receiver_bech32,
        gas_prices=f"{DEFAULT_GAS_AMT}{ibc_denom}",
    )
    assert return_rsp["code"] == 0, return_rsp["raw_log"]

    # Consumer spent at least `return_amt_wmantrausd` (plus fees).
    assert (
        consumer_cli.balance(receiver_bech32, denom=ibc_denom)
        <= consumer_ibc_bal_bf - return_amt_wmantrausd
    )

    def provider_received_wmantrausd_erc20() -> bool:
        return (
            wmantrausd.functions.balanceOf(receiver_evm).call()
            >= provider_wmantrausd_bal_bf + return_amt_wmantrausd
        )

    wait_for_fn(
        "provider wmantraUSD ERC20 after return", provider_received_wmantrausd_erc20
    )

    # 6) DistributionClaim precompile smoke test
    signer1, signer1_evm = provider_cli.address("signer1"), ADDRS["signer1"]
    val = provider_cli.address("validator", "val")

    delegate_amt = 20_000_000
    rsp = provider_cli.delegate_amount(
        val,
        f"{delegate_amt}{DEFAULT_DENOM}",
        _from=signer1,
        gas=250_000,
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    wait_for_new_blocks(provider_cli, 10)

    # pay consumer tx fees in the bridged denom after signer1 has delegated
    # when these fees are relayed back to the provider, unwrap to `erc20:<wmantraUSD>`
    fee_pay_rsp = consumer_cli.transfer(
        receiver_bech32,
        receiver_bech32,
        f"1{ibc_denom}",
        gas_prices=f"{DEFAULT_GAS_AMT}{ibc_denom}",
    )
    assert fee_pay_rsp["code"] == 0, fee_pay_rsp["raw_log"]
    wait_for_new_blocks(consumer_cli, 15)
    wait_for_new_blocks(provider_cli, 15)

    def signer1_has_wmantrausd_rewards() -> bool:
        try:
            raw = provider_cli.raw(
                "q",
                "distribution",
                "rewards",
                signer1,
                **provider_cli.get_base_kwargs(),
            )
            res = json.loads(raw)
        except Exception:
            return False

        total = res.get("total") or []
        if not isinstance(total, list) or len(total) == 0:
            return False

        for coin in total:
            if coin is None:
                continue
            try:
                denom = parse_denom(coin)
            except Exception:
                continue
            if denom != erc20_denom:
                continue
            try:
                return float(parse_amount(coin)) >= 1
            except Exception:
                return False

        return False

    wait_for_fn("signer1 wmantraUSD rewards", signer1_has_wmantrausd_rewards)

    bal_wmantrausd_bf = wmantrausd.functions.balanceOf(signer1_evm).call()
    bal_mantrausd_bf = mantrausd.functions.balanceOf(signer1_evm).call()

    max_retrieve = 10
    gas_limit = 650_000

    # Claim+convert happens atomically in a single tx (all-or-nothing).
    # This checks we don't end up with a leftover `erc20:<addr>` bank coin.
    assert provider_cli.balance(signer1, denom=erc20_denom) == 0

    claim_data = distribution_claim_call_data(
        signer1_evm,
        max_retrieve,
        erc20_denom,
    )

    expected_converted = decode(
        ["uint256"],
        w3.eth.call(
            {
                "to": DISTRIBUTION_CLAIM_ADDRESS,
                "from": signer1_evm,
                "data": claim_data,
                "gas": gas_limit,
            }
        ),
    )[0]
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

    bal_wmantrausd_af = wmantrausd.functions.balanceOf(signer1_evm).call()
    bal_mantrausd_af = mantrausd.functions.balanceOf(signer1_evm).call()

    w_delta = bal_wmantrausd_af - bal_wmantrausd_bf
    m_delta = bal_mantrausd_af - bal_mantrausd_bf

    # If the precompile unwraps, only dust (< SCALAR) remains as wmantraUSD.
    expected_underlying = expected_converted // SCALAR
    expected_dust = expected_converted - (expected_underlying * SCALAR)

    if m_delta > 0:
        assert m_delta == expected_underlying
        assert w_delta == expected_dust
    else:
        assert w_delta == expected_converted
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


@pytest.mark.parametrize("checksum", ["", "abc123def456"])
async def test_grant_and_revoke_role_as_admin(ibc, setup_consumer_accounts, checksum):
    await do_test_grant_and_revoke_role_as_admin(ibc.ibc2.async_w3, checksum)


@pytest.mark.parametrize("is_admin", [True, False])
async def test_grant_role_permissions(ibc, setup_consumer_accounts, is_admin):
    await do_test_grant_role_permissions(ibc.ibc2.async_w3, is_admin)


@pytest.mark.parametrize("is_admin", [True, False])
async def test_revoke_role_permissions(ibc, setup_consumer_accounts, is_admin):
    await do_test_revoke_role_permissions(ibc.ibc2.async_w3, is_admin)


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


async def test_remove_record(ibc, setup_consumer_accounts):
    await do_test_remove_record(ibc.ibc2.async_w3)


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

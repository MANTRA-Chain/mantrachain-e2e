import datetime
import json
import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest
import tomlkit
from eth_account import Account
from pystarport import cluster, ports
from pystarport.utils import wait_for_fn, wait_for_new_blocks, wait_for_port

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
    create_consumer_chain,
    send_transaction,
    update_consumer_chain,
)

pytestmark = pytest.mark.ccv

CONSUMER_DENOM = "anvnm"


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
        channel = "channel-1"
        denom = CONSUMER_DENOM
        denom_hash = ibc_denom_hash(f"{port}/{channel}/{denom}")
        owner_address = cli.address("validator")

        update_consumer_chain(
            cli,
            consumer_id,
            path,
            owner_address,
            authority,
            allowlisted_reward_denoms={"denoms": [f"ibc/{denom_hash}"]},
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
                CONSUMER_DENOM
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


async def test_ccv(ibc):
    cli = ibc.ibc1.cosmos_cli()
    cli2 = ibc.ibc2.cosmos_cli()
    provider_channel = "channel-0"
    res = cli.ibc_query_channel("provider", provider_channel).get("channel")
    assert res.get("state") == "STATE_OPEN"

    def check_channel_ready():
        try:
            res = cli.ibc_query_channel("transfer", "channel-1").get("channel")
        except Exception as e:
            print(f"channel-1 not ready: {e}")
            res = None
        return res is not None and res.get("state") == "STATE_OPEN"

    wait_for_fn("channel ready", check_channel_ready, timeout=30)

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
    denom = CONSUMER_DENOM
    rsp = cli2.transfer(
        cli2.address(community),
        cli2.address(signer),
        f"{amt}{denom}",
        gas_prices=f"{DEFAULT_GAS_AMT}{denom}",
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    assert w3.eth.get_balance(receiver) - balance == amt


async def test_add_registry(ibc, setup_consumer_accounts):
    await do_test_add_registry(ibc.ibc2.async_w3)


@pytest.mark.parametrize("checksum", ["", "abc123def456"])
async def test_grant_and_revoke_role_as_admin(ibc, setup_consumer_accounts, checksum):
    await do_test_grant_and_revoke_role_as_admin(ibc.ibc2.async_w3, checksum)


@pytest.mark.parametrize("is_admin", [True, False])
async def test_role_permissions(ibc, setup_consumer_accounts, is_admin):
    await do_test_grant_role_permissions(ibc.ibc2.async_w3, is_admin)
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

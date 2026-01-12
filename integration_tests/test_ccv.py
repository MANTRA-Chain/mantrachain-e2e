import datetime
import json
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest
import tomlkit
from pystarport import cluster, ports
from pystarport.utils import wait_for_fn, wait_for_new_blocks, wait_for_port

from .ibc_utils import IBCNetwork, create_channel, create_connection, ibc_denom_hash
from .network import Hermes, Mantra, setup_custom_mantra
from .utils import (
    ADDRS,
    CHAIN_ID,
    CMD,
    DEFAULT_DENOM,
    DEFAULT_GAS_AMT,
    KEYS,
    bech32_to_eth,
    find_log_event_attrs,
    send_transaction,
    update_node_cmd,
)

pytestmark = pytest.mark.ccv


def post_init(broken_binary):
    def inner(path, base_port, config, genesis):
        update_node_cmd(path / CHAIN_ID, broken_binary, 1)

    return inner


@pytest.fixture(scope="module")
def ibc(request, tmp_path_factory):
    b_chain_cmd = "inveniamd"
    if shutil.which(b_chain_cmd) is None:
        pytest.skip(f"{b_chain_cmd} not enabled")
    chain = request.config.getoption("chain_config")
    name = "configs/ibc_inveniamd.jsonnet"
    path = tmp_path_factory.mktemp("ibc_inveniamd")
    b_chain = "inveniam-canary-net-1"
    cmd = [
        "nix-build",
        "--no-out-link",
        Path(__file__).parent / "configs/provider.nix",
    ]
    print(*cmd)
    binary = Path(subprocess.check_output(cmd).strip().decode()) / f"bin/{CMD}"
    with contextmanager(setup_custom_mantra)(
        path,
        27400,
        Path(__file__).parent / name,
        relayer=cluster.Relayer.HERMES.value,
        post_init=post_init(binary),
        chain=chain,
        chain_binary=f"{b_chain_cmd},{str(binary)}",
    ) as ibc1:
        num_nodes = 3
        ibc2 = Mantra(ibc1.base_dir.parent / b_chain, chain_binary=b_chain_cmd)
        nodes = [f"{b_chain}-node{i}" for i in range(num_nodes)]
        ibc2.supervisorctl("stop", *nodes)
        cli = ibc1.cosmos_cli()
        # wait for grpc ready
        wait_for_port(ports.grpc_port(ibc1.base_port(0)))
        wait_for_new_blocks(cli, 1)
        now = datetime.datetime.now(datetime.UTC)
        dummy_hash = "2D5C2110941DA54BE07CBB9FACD7E4A2E3253E79BE7BE3E5A1A7BDA518BAA4BE"
        msg = {
            "chain_id": b_chain,
            "metadata": {
                "name": "name",
                "description": "description",
                "metadata": "metadata",
            },
            "initialization_parameters": {
                "initial_height": {"revision_number": 1, "revision_height": 1},
                "genesis_hash": dummy_hash,
                "binary_hash": dummy_hash,
                "spawn_time": now.isoformat().replace("+00:00", "Z"),
                "ccv_timeout_period": 2419200000000000,
                "unbonding_period": 80000000000,
                "transfer_timeout_period": 60000000000,
                "consumer_redistribution_fraction": "0.75",
                "blocks_per_distribution_transmission": 10,
                "historical_entries": 1000,
                "distribution_transmission_channel": "",
            },
            "power_shaping_parameters": {"top_N": 0},
        }
        msg_path = path / "create_msg.json"
        msg_path.write_text(json.dumps(msg))
        rsp = cli.provider_create_consumer(msg_path, from_="validator")
        assert rsp["code"] == 0, rsp["raw_log"]
        data = find_log_event_attrs(
            rsp["events"], "create_consumer", lambda attrs: "consumer_id" in attrs
        )
        consumer_id = data["consumer_id"]
        for i in range(num_nodes):
            rsp = ibc1.cosmos_cli(i=i).provider_opt_in(consumer_id, from_="validator")
            assert rsp["code"] == 0, rsp["raw_log"]

        authority = cli.get_params("marketmap").get("admin")
        now = datetime.datetime.now(datetime.UTC)
        port = "transfer"
        channel = "channel-1"
        denom = "anvnm"
        denom_hash = ibc_denom_hash(f"{port}/{channel}/{denom}")
        owner_address = cli.address("validator")
        update_msg = {
            "consumer_id": consumer_id,
            "owner_address": owner_address,
            "new_owner_address": authority,
            "metadata": msg["metadata"],
            "initialization_parameters": msg["initialization_parameters"]
            | {"spawn_time": now.isoformat().replace("+00:00", "Z")},
            "power_shaping_parameters": msg["power_shaping_parameters"]
            | {
                "validators_power_cap": 0,
                "validator_set_cap": 50,
                "allowlist": [],
                "denylist": [],
                "min_stake": 1000,
                "allow_inactive_vals": True,
                "prioritylist": [],
            },
            "allowlisted_reward_denoms": {"denoms": [f"ibc/{denom_hash}"]},
        }
        msg_path = path / "update_msg.json"
        msg_path.write_text(json.dumps(update_msg))
        rsp = cli.provider_update_consumer(msg_path, from_="validator")
        assert rsp["code"] == 0, rsp["raw_log"]

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
            genesis["app_state"]["ccvconsumer"]["params"]["reward_denoms"] = ["anvnm"]
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
        val = cli.debug_addr(bech32_to_eth(owner_address), bech="val")
        res = cli.delegations(owner_address)
        val = res[0]["delegation"]["validator_address"]
        delegate_amt = 10000000000000000000
        gas = 350_000
        coin = f"{delegate_amt}{DEFAULT_DENOM}"
        rsp = cli.delegate_amount(val, coin, _from="validator", gas=gas)
        assert rsp["code"] == 0, rsp["raw_log"]

        # wait enough for an epoch to elapse
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


def test_ccv(ibc):
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
    denom = "anvnm"
    rsp = cli2.transfer(
        cli2.address(community),
        cli2.address(signer),
        f"{amt}{denom}",
        gas_prices=f"{DEFAULT_GAS_AMT}{denom}",
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    assert w3.eth.get_balance(receiver) - balance == amt

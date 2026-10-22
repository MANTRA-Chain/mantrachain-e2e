import hashlib
import json
import math
import os
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

import requests
from eth_contract.erc20 import ERC20
from pystarport import cluster, ports
from pystarport.utils import (
    parse_amount,
    wait_for_fn_async,
    wait_for_new_blocks,
    wait_for_port,
)
from web3 import AsyncWeb3

from .cosmoscli import CosmosCLI
from .network import Hermes, Mantra, setup_custom_mantra
from .utils import (
    ACCOUNTS,
    ADDRESS_PREFIX,
    ADDRS,
    CHAIN_ID,
    CMD,
    DEFAULT_DENOM,
    KEYS,
    WETH_ADDRESS,
    build_and_deploy_contract_async,
    escrow_address,
    find_duplicate,
    find_fee,
    ibc_denom_address,
    parse_events_rpc,
    wait_for_balance_change,
)

RATE_LIMIT_CHANNEL = "channel-0"
# ibc-apps' rate-limiting v10 is the upstreamed Stride module, so it keeps
# Stride's REST path and ratelimit.v1 msgs
RATE_LIMIT_URL = "/Stride-Labs/ibc-rate-limiting/ratelimit"


class IBCNetwork(NamedTuple):
    ibc1: Mantra
    ibc2: Mantra
    hermes: Hermes | None


def hermes_cmd(hermes, *args):
    subprocess.check_call(["hermes", "--config", hermes.configpath, *args])


def add_key(hermes, chain, mnemonic_env, key_name):
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        f.write(os.getenv(mnemonic_env))
        path = f.name
    try:
        hermes_cmd(
            hermes,
            "keys",
            "add",
            "--hd-path",
            "m/44'/60'/0'/0/0",
            "--chain",
            chain,
            "--mnemonic-file",
            path,
            "--key-name",
            key_name,
            "--overwrite",
        )
    finally:
        os.unlink(path)


def call_hermes_cmd(hermes, b_chain):
    hermes_cmd(
        hermes,
        "create",
        "channel",
        "--a-port",
        "transfer",
        "--b-port",
        "transfer",
        "--a-chain",
        CHAIN_ID,
        "--b-chain",
        b_chain,
        "--new-client-connection",
        "--yes",
    )
    add_key(hermes, CHAIN_ID, "SIGNER1_MNEMONIC", "signer1")
    add_key(hermes, b_chain, "SIGNER2_MNEMONIC", "signer2")


def create_connection(hermes, chain_id):
    client_id = "07-tendermint-0"
    hermes_cmd(
        hermes,
        "create",
        "connection",
        "--a-chain",
        chain_id,
        "--a-client",
        client_id,
        "--b-client",
        client_id,
    )


def create_channel(hermes, chain_id, a_port, b_port):
    hermes_cmd(
        hermes,
        "create",
        "channel",
        "--a-chain",
        chain_id,
        "--a-port",
        a_port,
        "--b-port",
        b_port,
        "--order",
        "ordered",
        "--channel-version",
        "1",
        "--a-connection",
        "connection-0",
    )


def prepare_network(
    tmp_path,
    name,
    chain,
    b_chain="mantra-canary-net-2",
    cmd=CMD,
    post_init=None,
    chain_binary=None,
    genesis=None,
):
    name = f"configs/{name}.jsonnet"
    with contextmanager(setup_custom_mantra)(
        tmp_path,
        27000,
        Path(__file__).parent / name,
        relayer=cluster.Relayer.HERMES.value,
        chain=chain,
        post_init=post_init,
        chain_binary=chain_binary,
        genesis=genesis,
    ) as ibc1:
        cli = ibc1.cosmos_cli()
        ibc2 = Mantra(ibc1.base_dir.parent / b_chain, chain_binary=cmd)
        # wait for grpc ready
        wait_for_port(ports.grpc_port(ibc2.base_port(0)))
        wait_for_port(ports.grpc_port(ibc1.base_port(0)))
        wait_for_new_blocks(ibc2.cosmos_cli(), 1)
        wait_for_new_blocks(cli, 1)
        hermes = Hermes(ibc1.base_dir.parent / "relayer.toml")
        call_hermes_cmd(hermes, b_chain)
        ibc1.supervisorctl("start", "relayer-demo")
        yield IBCNetwork(ibc1, ibc2, hermes)


def run_hermes_transfer(
    hermes: Hermes,
    src_cli: CosmosCLI,
    src_addr: str,
    src_amt: int,
    dst_cli: CosmosCLI,
    dst_addr: str,
    denom=DEFAULT_DENOM,
    memo=None,
):
    # wait for hermes
    state = requests.get(f"http://127.0.0.1:{hermes.port}/state").json()
    assert state["status"] == "success", state
    hermes_cmd(
        hermes,
        "tx",
        "ft-transfer",
        "--dst-chain",
        dst_cli.chain_id,
        "--src-chain",
        src_cli.chain_id,
        "--src-port",
        "transfer",
        "--src-channel",
        "channel-0",
        "--amount",
        str(src_amt),
        "--timeout-height-offset",
        "1000",
        "--number-msgs",
        "1",
        "--denom",
        denom,
        "--receiver",
        dst_addr,
        "--key-name",
        src_addr,
        *(["--memo", memo] if memo else []),
    )


def assert_hermes_transfer(
    hermes: Hermes,
    src_cli: CosmosCLI,
    src_addr: str,
    src_amt: int,
    dst_cli: CosmosCLI,
    dst_addr: str,
    denom=DEFAULT_DENOM,
    prefix=ADDRESS_PREFIX,
) -> tuple[str, str]:
    escrow_addr = escrow_address("transfer", "channel-0", prefix=prefix)
    send_ibc_token = denom.startswith("ibc/")
    if send_ibc_token:
        dst_denom = src_cli.ibc_denom(denom).get("base")
    else:
        path = f"transfer/channel-0/{denom}"
        denom_hash = ibc_denom_hash(path)
        dst_denom = f"ibc/{denom_hash}"
    src_balance_bf = src_cli.balance(src_addr, denom)
    escrow_balance_bf = src_cli.balance(escrow_addr, denom)
    # baseline first, a fast relay can land before the send returns
    dst_balance_bf = dst_cli.balance(dst_addr, dst_denom)
    run_hermes_transfer(
        hermes, src_cli, src_addr, src_amt, dst_cli, dst_addr, denom=denom
    )
    fee = 0
    if not send_ibc_token and should_deduct_fee(hermes, src_cli.chain_id, denom):
        tx_events = latest_tx_events(src_cli, MSG_TRANSFER)
        fee = int(parse_amount(tx_events["tx"]["fee"]))
    dst_balance = wait_for_balance_change(dst_cli, dst_addr, dst_denom, dst_balance_bf)
    assert dst_balance == dst_balance_bf + src_amt
    if not send_ibc_token:
        assert dst_cli.ibc_denom_hash(path) == denom_hash
        assert src_cli.balance(escrow_addr, denom) == escrow_balance_bf + src_amt
    assert src_cli.balance(src_addr, denom) == src_balance_bf - src_amt - fee
    return dst_denom, dst_balance


def should_deduct_fee(hermes: Hermes, chain_id, denom: str) -> bool:
    for chain in hermes.config["chains"]:
        if chain["id"] == chain_id:
            return chain.get("gas_price", {}).get("denom") == denom
    return False


def assert_ibc_transfer(
    hermes: Hermes,
    src_cli,
    dst_cli: CosmosCLI,
    src_addr,
    dst_eth_addr: str,
    amt: int,
    dst_denom: str,
    denom=DEFAULT_DENOM,
    **kwargs,
) -> None:
    src_balance_bf = src_cli.balance(src_addr, denom=denom)
    # baseline first, a fast relay can land before the send returns
    dst_addr = dst_cli.debug_addr(dst_eth_addr, bech="acc")
    dst_balance_bf = dst_cli.balance(dst_addr, dst_denom)
    rsp = src_cli.ibc_transfer(
        dst_eth_addr, f"{amt}{denom}", "channel-0", from_=src_addr, **kwargs
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    fee = find_fee(rsp) if should_deduct_fee(hermes, src_cli.chain_id, denom) else 0
    dst_balance = wait_for_balance_change(dst_cli, dst_addr, dst_denom, dst_balance_bf)
    assert dst_balance == dst_balance_bf + amt
    assert src_cli.balance(src_addr, denom=denom) == src_balance_bf - amt - fee


def ibc_denom_hash(path):
    return hashlib.sha256(path.encode()).hexdigest().upper()


def query_rate_limit(chain, denom=DEFAULT_DENOM, channel=RATE_LIMIT_CHANNEL):
    port = ports.api_port(chain.base_port(0))
    url = f"http://127.0.0.1:{port}{RATE_LIMIT_URL}/ratelimit/{channel}/by_denom"
    rsp = requests.get(url, params={"denom": denom}).json()
    assert "rate_limit" in rsp, rsp
    return rsp["rate_limit"]


MSG_TRANSFER = "/ibc.applications.transfer.v1.MsgTransfer"
MSG_RECV_PACKET = "/ibc.core.channel.v1.MsgRecvPacket"
MSG_CHANNEL_OPEN_INIT = "/ibc.core.channel.v1.MsgChannelOpenInit"


def first_tx_by_action(cli, action):
    "The oldest tx carrying `action`."
    return cli.tx_search(f"message.action='{action}'")["txs"][0]


def latest_tx_events(cli, action):
    "Decoded events of the most recent tx carrying `action`."
    tx = cli.tx_search(f"message.action='{action}'", order_by="desc", limit=1)["txs"][0]
    return parse_events_rpc(tx["events"])


def assert_receiver_events(cli, cli2: CosmosCLI, dst_eth_addr: str):
    events = latest_tx_events(cli, MSG_TRANSFER)
    assert events.get("ibc_transfer").get("receiver") == dst_eth_addr

    events = latest_tx_events(cli2, MSG_RECV_PACKET)
    assert events.get("fungible_token_packet").get("receiver") == dst_eth_addr


def assert_dynamic_fee(cli):
    # assert that the relayer transactions do enables the dynamic fee extension option.
    tx = first_tx_by_action(cli, MSG_CHANNEL_OPEN_INIT)
    fee = int(parse_amount(parse_events_rpc(tx["events"])["tx"]["fee"]))
    gas = int(tx["gas_wanted"])
    # the effective fee is decided by the max_priority_fee (base fee is zero)
    # rather than the normal gas price
    cosmos_evm_dynamic_fee = 10000000000000000 / 10**18
    assert fee == math.ceil(gas * cosmos_evm_dynamic_fee)


def assert_dup_events(cli):
    # check duplicate OnRecvPacket events
    for event in first_tx_by_action(cli, MSG_RECV_PACKET)["events"]:
        dup = find_duplicate(event["attributes"])
        assert not dup, f"duplicate {dup} in {event['type']}"


async def assert_ibc_transfer_flow(
    ibc: IBCNetwork,
    denom=DEFAULT_DENOM,
    chain2_denom="atest",
    chain2_prefix="cosmos",
    return_ratio=1,
    upgrade_cb=None,
) -> str:
    w3 = ibc.ibc1.async_w3
    cli1 = ibc.ibc1.cosmos_cli()
    cli2 = ibc.ibc2.cosmos_cli()
    chain2_gas_prices = f"10000000000{chain2_denom}"
    amt = 100
    amt2 = 2
    amt3 = 3
    amt4 = 4
    eth_community = ADDRS["community"]
    for c in [cli1, cli2]:
        add_key(ibc.hermes, c.chain_id, "COMMUNITY_MNEMONIC", "community")

    print(f"chain2 signer2 -> chain1 signer1 {amt}{chain2_denom}")
    dst_denom, _ = assert_hermes_transfer(
        ibc.hermes,
        cli2,
        "signer2",
        amt,
        cli1,
        cli1.address("signer1"),
        denom=chain2_denom,
        prefix=chain2_prefix,
    )
    # skipped on the upgrade test, whose genesis binary predates the current
    # extension_options; worth re-enabling once that binary supports them
    if not upgrade_cb:
        assert_dynamic_fee(cli1)
    assert_dup_events(cli1)
    ibc_erc20_addr = ibc_denom_address(dst_denom)
    assert (await ERC20.fns.decimals().call(w3, to=ibc_erc20_addr)) == 0
    assert await ERC20.fns.totalSupply().call(w3, to=ibc_erc20_addr) == amt

    print(f"chain1 signer1 -> chain2 signer2 {amt2}{denom}")
    dst_denom2, _ = assert_hermes_transfer(
        ibc.hermes,
        cli1,
        "signer1",
        amt2,
        cli2,
        cli2.address("signer2"),
        denom=denom,
    )

    print(f"chain1 community -> chain2 eth_community {amt3}{denom}")
    dst_denom3 = f"ibc/{ibc_denom_hash(f'transfer/channel-0/{denom}')}"
    assert_ibc_transfer(
        ibc.hermes,
        cli1,
        cli2,
        "community",
        eth_community,
        amt3,
        dst_denom3,
        denom=denom,
    )
    assert_receiver_events(cli1, cli2, eth_community)

    print(f"chain2 community -> chain1 eth_community {amt4}{chain2_denom}")
    dst_denom4 = f"ibc/{ibc_denom_hash(f'transfer/channel-0/{chain2_denom}')}"
    assert_ibc_transfer(
        ibc.hermes,
        cli2,
        cli1,
        "community",
        eth_community,
        amt4,
        dst_denom4,
        denom=chain2_denom,
        gas_prices=chain2_gas_prices,
    )
    assert_receiver_events(cli2, cli1, eth_community)

    if upgrade_cb:
        upgrade_cb()

    amt = int(amt * return_ratio)
    print(f"chain1 signer1 -> chain2 signer2 back {amt}{dst_denom}")
    assert_hermes_transfer(
        ibc.hermes,
        cli1,
        "signer1",
        amt,
        cli2,
        cli2.address("signer2"),
        denom=dst_denom,
    )

    amt2 = int(amt2 * return_ratio)
    print(f"chain2 signer2 -> chain1 signer1 back {amt2}{dst_denom2}")
    assert_hermes_transfer(
        ibc.hermes,
        cli2,
        "signer2",
        amt2,
        cli1,
        cli1.address("signer1"),
        denom=dst_denom2,
        prefix=chain2_prefix,
    )

    amt3 = int(amt3 * return_ratio)
    print(f"chain2 community -> chain1 eth_community back {amt3}{dst_denom3}")
    assert_ibc_transfer(
        ibc.hermes,
        cli2,
        cli1,
        "community",
        eth_community,
        amt3,
        denom,
        denom=dst_denom3,
        gas_prices=chain2_gas_prices,
    )
    assert_receiver_events(cli2, cli1, eth_community)

    amt4 = int(amt4 * return_ratio)
    print(f"chain1 community -> chain2 eth_community back {amt4}{dst_denom4}")
    assert_ibc_transfer(
        ibc.hermes,
        cli1,
        cli2,
        "community",
        eth_community,
        amt4,
        chain2_denom,
        denom=dst_denom4,
    )
    assert_receiver_events(cli1, cli2, eth_community)
    return ibc_erc20_addr


async def wait_for_balance_change_async(
    w3: AsyncWeb3, addr, token_addr: str, init_balance: int
):
    async def check_balance():
        current_balance = await ERC20.fns.balanceOf(addr).call(w3, to=token_addr)
        return current_balance if current_balance != init_balance else None

    return await wait_for_fn_async("balance change", check_balance)


def ibc_timeout_ns(seconds=600):
    return int((time.time() + seconds) * 10**9)


async def build_ics20_tx(
    fn,
    *,
    sender,
    denom,
    amt,
    receiver,
    memo,
    timeout_timestamp=None,
    port="transfer",
    channel="channel-0",
    timeout_height=(0, 0),
    gas=900_000,
):
    """Build a tx for a CounterWithCallbacks entrypoint taking ICS20 args.

    Both entrypoints take the same eight positionals, so the order is spelled
    out once here. Pass `timeout_timestamp` to share one deadline across txs.
    """
    if timeout_timestamp is None:
        timeout_timestamp = ibc_timeout_ns()
    return await fn(
        port,
        channel,
        denom,
        amt,
        receiver,
        timeout_height,
        timeout_timestamp,
        memo,
    ).build_transaction({"from": sender, "gas": gas})


async def prepare_src_callback(w3, funder_name: str, amt: int, gas=400_000):
    contract = await build_and_deploy_contract_async(
        w3, "CounterWithCallbacks", key=KEYS[funder_name]
    )
    cb_balance_bf = await ERC20.fns.balanceOf(contract.address).call(
        w3, to=WETH_ADDRESS
    )
    receipt = await ERC20.fns.transfer(contract.address, amt).transact(
        w3, ACCOUNTS[funder_name], to=WETH_ADDRESS, gas=gas
    )
    assert receipt["status"] == 1
    await wait_for_balance_change_async(
        w3, contract.address, WETH_ADDRESS, cb_balance_bf
    )
    # send from contract via ICS20 with src_callback memo pointing to itself.
    src_cb = {
        "src_callback": {
            "address": contract.address,
            "gas_limit": "1000000",
        }
    }
    return contract, json.dumps(src_cb)

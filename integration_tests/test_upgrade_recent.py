import json
import subprocess

import pytest
import tomlkit
from pystarport import ports
from pystarport.utils import wait_for_new_blocks, wait_for_port

from .network import Mantra
from .upgrade_utils import (
    LEGACY_DENOM,
    cleanup_upgrades_folder,
    do_upgrade,
    setup_mantra_upgrade,
)
from .utils import (
    ADDRS,
    CHAIN_ID,
    DEFAULT_DENOM,
    SCALE_FACTOR,
    AsyncGreeter,
    approve_proposal,
    assert_withdraw_rewards,
    call_with_retry_async,
    module_address,
    update_node_cmd,
    verify_tax_distribution,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.skipped]


@pytest.fixture(scope="module")
def custom_mantra(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    yield from setup_mantra_upgrade(
        tmp_path_factory,
        "upgrade-test-package-recent",
        "cosmovisor_recent",
        "genesis",
        chain=chain,
        port=27010,
    )


async def exec(c, tmp_path):
    cli = c.cosmos_cli()
    w3 = c.async_w3
    grpc_cmd = cli.raw.cmd
    community = ADDRS["community"]
    gas_prices = f"1{LEGACY_DENOM}"
    greeter = AsyncGreeter()
    await greeter.deploy(w3)

    old_height = cli.block_height()
    assert "Hello" == await greeter.greet(block_identifier=old_height)

    balance_bf = await w3.eth.get_balance(community, block_identifier=old_height)
    wait_height = 30

    scam_addr = cli.address("scammer")
    delegated_vesting_amts = [100000, 70000]
    UOM_PER_OM = 1_000_000
    transfer_amt = 1

    rsp = cli.transfer(
        cli.address("community"),
        scam_addr,
        f"{transfer_amt * UOM_PER_OM}{LEGACY_DENOM}",
        gas_prices=gas_prices,
    )
    assert rsp["code"] == 0, rsp["raw_log"]

    validators = cli.validators()
    val_ops = [v["operator_address"] for v in validators[:2]]
    total_delegated = 0
    for amt in delegated_vesting_amts:
        delegated_vesting_amt = amt * UOM_PER_OM
        rsp = cli.delegate_amount(
            val_ops[0],
            f"{delegated_vesting_amt}{LEGACY_DENOM}",
            _from="scammer",
            gas=220000,
            gas_prices=gas_prices,
        )
        assert rsp["code"] == 0, rsp["raw_log"]
        total_delegated += delegated_vesting_amt
        delegations_bf = cli.delegation(scam_addr, val_ops[0])["balance"]["amount"]
        assert int(delegations_bf) == total_delegated

    msg = {
        "@type": "/mantrachain.sanction.v1.MsgAddBlacklistAccounts",
        "authority": module_address("gov"),
        "blacklist_accounts": [scam_addr],
    }
    proposal_src = {
        "title": "Blacklist scam address",
        "summary": "Add scam vesting account to blacklist",
        "deposit": f"1{LEGACY_DENOM}",
        "messages": [msg],
    }
    proposal_file = tmp_path / "blacklist_proposal_recent.json"
    proposal_file.write_text(json.dumps(proposal_src))
    gov_rsp = cli.submit_gov_proposal(
        proposal_file, from_="community", gas_prices=gas_prices
    )
    assert gov_rsp["code"] == 0, gov_rsp["raw_log"]
    approve_proposal(c, gov_rsp["events"], gas_prices=gas_prices)
    assert scam_addr in cli.query_blacklist()

    def cb(cli):
        wait_for_new_blocks(cli, 2)
        stop_height = cli.block_height()
        c.supervisorctl("stop", f"{CHAIN_ID}-node1")
        update_node_cmd(c.base_dir, grpc_cmd, 1, grpc_only=True)
        target_height = stop_height + wait_height
        cli = do_upgrade(c, "v7.0.0-rc4", target_height, denom=LEGACY_DENOM)
        return cli, target_height

    target_height = assert_withdraw_rewards(
        c, cb, denom=LEGACY_DENOM, scale=SCALE_FACTOR, gas_prices=gas_prices
    )
    stop_height = target_height - wait_height

    c.supervisorctl("start", "mantra-canary-net-1-node0")
    wait_for_new_blocks(c.cosmos_cli(), 1)

    verify_tax_distribution(
        cli,
        target_height,
        denom=LEGACY_DENOM,
        scale_factor=SCALE_FACTOR,
    )

    scam_balance_bf = int(cli.balance(scam_addr, DEFAULT_DENOM))
    wait_for_new_blocks(cli, 5)
    target_height2 = cli.block_height() + wait_height
    cli = do_upgrade(c, "v7.0.0-rc5", target_height2, scale=SCALE_FACTOR)
    pending_rewards = int(
        cli.distribution_rewards(scam_addr, height=target_height2 - 1)
    )
    assert int(cli.delegation(scam_addr, val_ops[0])["balance"]["amount"]) == 0
    unbonding = cli.undelegation(scam_addr, val_ops[0])
    assert unbonding.get("entries")
    assert (
        sum(int(entry["balance"]) for entry in unbonding["entries"])
        == sum(delegated_vesting_amts) * UOM_PER_OM * SCALE_FACTOR
    )
    scam_balance_af = int(cli.balance(scam_addr, DEFAULT_DENOM))
    balance_diff = scam_balance_af - scam_balance_bf
    assert balance_diff >= pending_rewards
    assert balance_diff / SCALE_FACTOR == pending_rewards / SCALE_FACTOR

    grpc_node = 1
    api_port = ports.api_port(c.base_port(grpc_node))
    grpc_port = ports.grpc_port(c.base_port(grpc_node))

    def start_grpc_node(logfile):
        return subprocess.Popen(
            [grpc_cmd, "start", "--grpc-only", "--home", c.base_dir / "node1"],
            stdout=logfile,
            stderr=subprocess.STDOUT,
        )

    async def test_historical_queries():
        data = greeter.contract.fns.setGreeting("world").data
        tx = {"to": greeter.address, "from": community, "data": data}
        assert await greeter.greet(block_identifier=old_height) == "Hello"
        assert await w3.eth.estimate_gas(tx, block_identifier=old_height) > 0
        assert (
            await w3.eth.get_balance(community, block_identifier=old_height)
            == balance_bf
        )

    async def query_greeter():
        return await greeter.greet(block_identifier=old_height)

    # run grpc-only mode directly with existing chain state
    with (c.base_dir / "node1.log").open("a") as logfile:
        proc = start_grpc_node(logfile)

        try:
            for port in (grpc_port, api_port):
                wait_for_port(port)

            cli = c.cosmos_cli()
            c.supervisorctl("stop", f"{CHAIN_ID}-node0")
            path = cli.data_dir / "config/app.toml"
            cfg = tomlkit.parse(path.read_text())
            backup_config = json.dumps({f"127.0.0.1:{grpc_port}": [0, stop_height]})
            cfg["grpc"]["historical-grpc-address-block-range"] = backup_config
            path.write_text(tomlkit.dumps(cfg))
            c.supervisorctl("start", f"{CHAIN_ID}-node0")
            wait_for_new_blocks(cli, 1)

            evmrpc_port = ports.evmrpc_port(c.base_port(0))
            wait_for_port(evmrpc_port)

            # test historical contract calls
            test_historical_queries()

            # test restart grpc-only node
            proc.terminate()
            proc.wait(timeout=5)

            assert await call_with_retry_async(query_greeter, expect_error=True)

            balance = await w3.eth.get_balance(community)
            proc = start_grpc_node(logfile)
            for port in (grpc_port, api_port):
                wait_for_port(port)
            wait_for_new_blocks(cli, 1)

            assert await call_with_retry_async(query_greeter, expect_error=False)
            # test historical queries work after reconnection
            await test_historical_queries()
            assert await w3.eth.get_balance(community) == balance
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait()


async def test_cosmovisor_upgrade(custom_mantra: Mantra, tmp_path):
    await exec(custom_mantra, tmp_path)
    cleanup_upgrades_folder(custom_mantra.cosmos_cli().data_dir)

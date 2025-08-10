import asyncio
from collections import defaultdict
from itertools import groupby
from pathlib import Path

import pytest

from .network import setup_custom_mantra
from .utils import (
    DEFAULT_DENOM,
    assert_transfer,
    module_address,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def custom_mantra(tmp_path_factory):
    path = tmp_path_factory.mktemp("permission")
    yield from setup_custom_mantra(
        path, 26700, Path(__file__).parent / "configs/accounts.jsonnet"
    )


async def transfer(cli, user, addr_b):
    nonce_locks = defaultdict(asyncio.Lock)
    async with nonce_locks[user]:
        rsp = await asyncio.to_thread(
            cli.transfer, user, addr_b, f"1{DEFAULT_DENOM}", event_query_tx=False
        )
    rsp = await asyncio.to_thread(cli.event_query_tx_for, rsp["txhash"])
    assert rsp["code"] == 4, rsp["raw_log"]
    assert f"{addr_b} is not allowed to receive funds" in rsp["raw_log"]
    return rsp


async def execute_user_transfers(cli, user_modules):
    results = []
    for user_name, module in user_modules:
        addr_b = module_address(module)
        result = await transfer(cli, user_name, addr_b)
        results.append(result)
    return results


async def test_transfers_not_allowed(custom_mantra):
    cli = custom_mantra.cosmos_cli()
    modules = [
        "bonded_tokens_pool",
        "distribution",
        "erc20",
        "evm",
        "fee_collector",
        "feemarket",
        "gov",
        "interchainaccounts",
        "mint",
        "nft",
        "not_bonded_tokens_pool",
        "oracle",
        "precisebank",
        "ratelimit",
        "sanction",
        "tax",
        "tokenfactory",
        "transfer",
        "wasm",
    ]
    users = cli.list_accounts()
    users = [user["name"] for user in users if user["name"] != "reserve"]
    pairs = []
    for i, module in enumerate(modules):
        user = users[i % len(users)]
        pairs.append((user, module))

    user_groups = {}
    for user, group in groupby(sorted(pairs), key=lambda x: x[0]):
        user_groups[user] = list(group)

    user_tasks = [
        execute_user_transfers(cli, modules) for _, modules in user_groups.items()
    ]

    await asyncio.gather(*user_tasks)
    assert_transfer(cli, cli.address("validator"), cli.address("community"))

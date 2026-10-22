import asyncio
from collections import defaultdict
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
def custom_mantra(request, tmp_path_factory):
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp("permission")
    yield from setup_custom_mantra(
        path,
        26700,
        Path(__file__).parent / "configs/accounts.jsonnet",
        chain=chain,
    )


def transfer_not_allowed(cli, user, module):
    "A send from `user` to `module`'s account is rejected when it executes."
    addr = module_address(module)
    rsp = cli.transfer(user, addr, f"1{DEFAULT_DENOM}", event_query_tx=False)
    rsp = cli.event_query_tx_for(rsp["txhash"])
    assert rsp["code"] == 4, rsp["raw_log"]
    assert f"{addr} is not allowed to receive funds" in rsp["raw_log"]


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
        "ratelimit",
        "tax",
        "tokenfactory",
        "transfer",
    ]
    modules2 = [
        "sanction",
        "wasm",
    ]
    modules.extend(module for module in modules2 if cli.has_module(module))
    users = [user["name"] for user in cli.list_accounts() if user["name"] != "reserve"]
    # spread the modules over the users; each user sends in turn, users in parallel
    groups = defaultdict(list)
    for i, module in enumerate(modules):
        groups[users[i % len(users)]].append(module)

    async def send_all(user, user_modules):
        for module in user_modules:
            await asyncio.to_thread(transfer_not_allowed, cli, user, module)

    await asyncio.gather(*(send_all(u, mods) for u, mods in groups.items()))
    assert_transfer(cli, cli.address("community"), cli.address("signer1"))

import pytest

from .ibc_utils import (
    RATE_LIMIT_CHANNEL,
    ibc_denom_hash,
    prepare_network,
    query_rate_limit,
)
from .utils import (
    DEFAULT_DENOM,
    module_address,
    submit_gov_proposal,
    wait_for_balance_change,
)

pytestmark = pytest.mark.slow

MAX_PERCENT_SEND = 1


@pytest.fixture(scope="module")
def ibc(request, tmp_path_factory):
    "prepare-network"
    name = "ibc"
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp("ibc-rate-limit")
    yield from prepare_network(path, name, chain)


def test_rate_limited_transfer(ibc, tmp_path):
    """Sends over the quota are rejected on the ICS4 send path."""
    cli = ibc.ibc1.cosmos_cli()
    cli2 = ibc.ibc2.cosmos_cli()
    community = cli.address("community")
    receiver = cli2.address("community")

    msg = {
        "@type": "/ratelimit.v1.MsgAddRateLimit",
        "authority": module_address("gov"),
        "denom": DEFAULT_DENOM,
        "channel_or_client_id": RATE_LIMIT_CHANNEL,
        "max_percent_send": str(MAX_PERCENT_SEND),
        "max_percent_recv": "100",
        "duration_hours": "24",
    }
    # the default 200k gas falls just short of the proposal's deposit write
    submit_gov_proposal(ibc.ibc1, tmp_path, [msg], gas=300000)

    limit = query_rate_limit(ibc.ibc1)
    assert limit["quota"]["max_percent_send"] == str(MAX_PERCENT_SEND), limit
    quota = int(limit["flow"]["channel_value"]) * MAX_PERCENT_SEND // 100
    balance = cli.balance(community)
    assert (
        balance > quota + 10**18
    ), f"community balance {balance} cannot exceed the {quota} send quota"

    # one send over the quota is rejected by the rate-limiting middleware
    rsp = cli.ibc_transfer(
        receiver, f"{quota + 1}{DEFAULT_DENOM}", RATE_LIMIT_CHANNEL, from_=community
    )
    assert rsp["code"] != 0, rsp
    assert "quota" in rsp["raw_log"], rsp["raw_log"]

    # an in-quota send passes and its outflow is recorded
    amt = 10**18
    path = f"transfer/{RATE_LIMIT_CHANNEL}/{DEFAULT_DENOM}"
    dst_denom = f"ibc/{ibc_denom_hash(path)}"
    balance_bf = cli2.balance(receiver, dst_denom)
    rsp = cli.ibc_transfer(
        receiver, f"{amt}{DEFAULT_DENOM}", RATE_LIMIT_CHANNEL, from_=community
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    assert wait_for_balance_change(cli2, receiver, dst_denom, balance_bf) == (
        balance_bf + amt
    )
    assert int(query_rate_limit(ibc.ibc1)["flow"]["outflow"]) == amt

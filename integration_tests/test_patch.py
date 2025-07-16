import pytest

from .utils import eth_to_bech32, module_address, submit_gov_proposal

pytestmark = pytest.mark.slow


def test_int_overflow(mantra, tmp_path):
    cli = mantra.cosmos_cli()
    name = "validator"
    bech32_addr = cli.address(name)
    val_addr = cli.address(name, "val")
    rsp = cli.set_withdraw_addr(bech32_addr, from_=name)
    assert rsp["code"] == 0, rsp["raw_log"]
    assert not cli.query_disabled_list()
    msg_type_urls = ["/cosmos.distribution.v1beta1.MsgDepositValidatorRewardsPool"]
    submit_gov_proposal(
        mantra,
        tmp_path,
        messages=[
            {
                "@type": "/cosmos.circuit.v1.MsgTripCircuitBreaker",
                "authority": eth_to_bech32(module_address("gov")),
                "msg_type_urls": msg_type_urls,
            }
        ],
    )
    assert cli.query_disabled_list() == msg_type_urls

    # fund validator rewards pool
    denom = "utesttest"
    delegation_amt_w_denom = f"115792089237316195423570985008687907853269984665640564039457584007913129639935{denom}"  # noqa: E501
    rsp = cli.fund_validator_rewards_pool(
        val_addr,
        delegation_amt_w_denom,
        from_=name,
    )
    assert rsp["code"] != 0
    assert "tx type not allowed" in rsp["raw_log"]

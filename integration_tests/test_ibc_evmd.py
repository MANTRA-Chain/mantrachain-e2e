import pytest
from eth_contract.erc20 import ERC20
from pystarport.utils import wait_for_fn_async

from .ibc_utils import (
    assert_ibc_transfer_flow,
    build_ics20_tx,
    ibc_timeout_ns,
    prepare_network,
    prepare_src_callback,
)
from .utils import (
    ACCOUNTS,
    ADDRS,
    DEFAULT_GAS_AMT,
    WETH_ADDRESS,
    assert_create_erc20_denom,
    eth_to_bech32,
    send_transaction_async,
)

pytestmark = pytest.mark.slow
gas = 400_000


@pytest.fixture(scope="module")
def ibc(request, tmp_path_factory):
    "prepare-network"
    name = "ibc_evmd"
    chain = request.config.getoption("chain_config")
    path = tmp_path_factory.mktemp(name)
    yield from prepare_network(
        path, name, chain, b_chain="evm-canary-net-1", cmd="evmd"
    )


async def test_ibc_transfer(ibc):
    await assert_ibc_transfer_flow(ibc)


async def test_ibc_src_ack_nested_forward_blocked(ibc):
    w3 = ibc.ibc2.async_w3
    cli = ibc.ibc2.cosmos_cli()
    signer2 = ADDRS["signer2"]

    erc20_denom, total = await assert_create_erc20_denom(w3, signer2)
    denom = "atest"
    res = cli.register_erc20(
        WETH_ADDRESS, _from="community", gas=gas, gas_prices=f"{DEFAULT_GAS_AMT}{denom}"
    )
    assert res["code"] == 0, res

    send_amt = total // 10
    cb, src_cb_memo = await prepare_src_callback(w3, "signer2", send_amt)

    # fund contract so nested forward would succeed if not blocked
    extra_funding = send_amt
    receipt = await ERC20.fns.transfer(cb.address, extra_funding).transact(
        w3, ACCOUNTS["signer2"], to=WETH_ADDRESS, gas=gas
    )
    assert receipt["status"] == 1

    addr_signer1 = eth_to_bech32(ADDRS["signer1"])
    # one deadline for both txs, so the forward inherits the transfer's timeout
    timeout_timestamp = ibc_timeout_ns()

    # configure callback contract to attempt a nested ICS20 transfer on ack
    nested_amt = max(1, send_amt // 2)
    cfg_tx = await build_ics20_tx(
        cb.functions.configureNestedAckForward,
        sender=signer2,
        denom=erc20_denom,
        amt=nested_amt,
        receiver=addr_signer1,
        memo="",
        timeout_timestamp=timeout_timestamp,
    )
    cfg_receipt = await send_transaction_async(w3, ACCOUNTS["signer2"], **cfg_tx)
    assert cfg_receipt["status"] == 1

    tx = await build_ics20_tx(
        cb.functions.ibcTransfer,
        sender=signer2,
        denom=erc20_denom,
        amt=send_amt,
        receiver=addr_signer1,
        memo=src_cb_memo,
        timeout_timestamp=timeout_timestamp,
    )

    txreceipt = await send_transaction_async(w3, ACCOUNTS["signer2"], **tx)
    assert txreceipt["status"] == 1

    async def check_nested_attempted():
        attempted = await cb.functions.nestedAckForwardAttempted().call()
        return attempted if attempted else None

    await wait_for_fn_async("nested ack forward attempted", check_nested_attempted)

    attempted = await cb.functions.nestedAckForwardAttempted().call()
    assert attempted is True
    nested_succeeded = await cb.functions.nestedAckForwardSucceeded().call()
    assert nested_succeeded is False

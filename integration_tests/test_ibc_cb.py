import hashlib
import json

import pytest
from eth_contract.deploy_utils import (
    ensure_create2_deployed,
    ensure_deployed_by_create2,
)
from eth_contract.erc20 import ERC20
from eth_contract.utils import get_initcode
from eth_contract.weth import WETH

from .ibc_utils import hermes_transfer, prepare_network
from .utils import (
    ADDRS,
    CONTRACTS,
    KEYS,
    WETH9_ARTIFACT,
    WETH_ADDRESS,
    WETH_SALT,
    deploy_contract_async,
    eth_to_bech32,
    generate_isolated_address,
    module_address,
    submit_gov_proposal,
    wait_for_fn,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def ibc(tmp_path_factory):
    "prepare-network"
    name = "ibc"
    path = tmp_path_factory.mktemp(name)
    yield from prepare_network(path, name)


async def test_ibc_transfer(ibc, tmp_path):
    w3 = ibc.ibc1.async_w3
    cli = ibc.ibc1.cosmos_cli()
    cli2 = ibc.ibc2.cosmos_cli()
    signer1 = ADDRS["signer1"]
    signer2 = ADDRS["signer2"]
    addr_signer1 = eth_to_bech32(signer1)
    addr_signer2 = eth_to_bech32(signer2)
    await ensure_create2_deployed(w3, signer1)
    await ensure_deployed_by_create2(
        w3,
        signer1,
        get_initcode(WETH9_ARTIFACT),
        salt=WETH_SALT,
    )

    # check native erc20 transfer
    submit_gov_proposal(
        ibc.ibc1,
        tmp_path,
        messages=[
            {
                "@type": "/cosmos.evm.erc20.v1.MsgRegisterERC20",
                "signer": eth_to_bech32(module_address("gov")),
                "erc20addresses": [WETH_ADDRESS],
            }
        ],
    )

    assert (await ERC20.fns.decimals().call(w3, to=WETH_ADDRESS)) == 18
    total = await ERC20.fns.totalSupply().call(w3, to=WETH_ADDRESS)
    signer1_balance_eth_bf = await ERC20.fns.balanceOf(signer1).call(
        w3, to=WETH_ADDRESS
    )
    assert total == signer1_balance_eth_bf == 0

    weth = WETH(to=WETH_ADDRESS)
    erc20_denom = f"erc20:{WETH_ADDRESS}"
    deposit_amt = 100
    res = await weth.fns.deposit().transact(w3, signer1, value=deposit_amt)
    assert res.status == 1
    total = await ERC20.fns.totalSupply().call(w3, to=WETH_ADDRESS)
    signer1_balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=WETH_ADDRESS)
    assert total == signer1_balance_eth == deposit_amt
    signer1_balance_eth_bf = signer1_balance_eth

    # mantra-canary-net-1 signer1 -> mantra-canary-net-2 signer2 50erc20_denom
    erc20_transfer_amt = deposit_amt // 2
    src_chain = "mantra-canary-net-1"
    dst_chain = "mantra-canary-net-2"
    channel = "channel-0"
    isolated = generate_isolated_address(channel, addr_signer2)

    path, escrow_addr = hermes_transfer(
        ibc, src_chain, dst_chain, erc20_transfer_amt, addr_signer2, denom=erc20_denom
    )

    denom_hash = hashlib.sha256(path.encode()).hexdigest().upper()
    dst_denom = f"ibc/{denom_hash}"
    signer2_balance_bf = cli2.balance(addr_signer2, dst_denom)
    signer2_balance = 0

    def check_balance_change():
        nonlocal signer2_balance
        signer2_balance = cli2.balance(addr_signer2, dst_denom)
        return signer2_balance != signer2_balance_bf

    wait_for_fn("balance change", check_balance_change)
    assert signer2_balance == signer2_balance_bf + erc20_transfer_amt
    assert cli2.ibc_denom_hash(path) == denom_hash
    signer2_balance_bf = signer2_balance

    assert cli.balance(escrow_addr, erc20_denom) == erc20_transfer_amt
    signer1_balance_eth = await ERC20.fns.balanceOf(signer1).call(w3, to=WETH_ADDRESS)
    assert signer1_balance_eth == signer1_balance_eth_bf - erc20_transfer_amt

    # convert all erc20 for signer1
    signer1_balance_erc20_denom_bf = cli.balance(addr_signer1, erc20_denom)
    rsp = cli.convert_erc20(
        WETH_ADDRESS,
        signer1_balance_eth,
        _from=addr_signer1,
        gas=999999,
    )
    assert rsp["code"] == 0, rsp["raw_log"]
    assert await ERC20.fns.balanceOf(signer1).call(w3, to=WETH_ADDRESS) == 0
    assert (
        cli.balance(addr_signer1, erc20_denom)
        == signer1_balance_erc20_denom_bf + signer1_balance_eth
    )
    assert cli.balance(escrow_addr, erc20_denom) == erc20_transfer_amt

    # deploy cb contract
    cb_contract = await deploy_contract_async(
        w3,
        CONTRACTS["CounterWithCallbacks"],
        KEYS["signer1"],
    )
    cb_amt = 2
    calldata = await cb_contract.functions.add(WETH_ADDRESS, cb_amt).build_transaction(
        {"from": signer1, "gas": 210000}
    )
    calldata = calldata["data"][2:]
    dest_cb = {
        "dest_callback": {
            "address": cb_contract.address,
            "gas_limit": 1000000,
            "calldata": calldata,
        }
    }
    dest_cb = json.dumps(dest_cb)

    # mantra-canary-net-2 signer2 -> mantra-canary-net-1 signer1 2erc20_denom
    src_chain = "mantra-canary-net-2"
    dst_chain = "mantra-canary-net-1"
    hermes_transfer(
        ibc, src_chain, dst_chain, cb_amt, isolated, denom=dst_denom, memo=dest_cb
    )
    assert cli2.balance(addr_signer2, dst_denom) == signer2_balance_bf - cb_amt

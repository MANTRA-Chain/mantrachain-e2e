import pytest
from pystarport import ports

from .utils import (
    ADDRS,
    KEYS,
    modify_command_in_supervisor_config,
    send_txs,
    wait_for_port,
)

origin_cmd = None


@pytest.mark.unmarked
@pytest.mark.parametrize("max_gas_wanted", [80000000, 40000000, 25000000, 500000, None])
def test_tx_inclusion(mantra, max_gas_wanted):
    """
    - send multiple heavy transactions at the same time.
    - check they are included in consecutively blocks without failure.

    test against different max-gas-wanted configuration.
    """

    def fn(cmd):
        global origin_cmd
        if origin_cmd is None:
            origin_cmd = cmd
        if max_gas_wanted is None:
            return origin_cmd
        return f"{origin_cmd} --evm.max-tx-gas-wanted {max_gas_wanted}"

    modify_command_in_supervisor_config(
        mantra.base_dir / "tasks.ini",
        lambda cmd: fn(cmd),
        mantra.chain_binary,
    )
    mantra.supervisorctl("update")
    wait_for_port(ports.evmrpc_port(mantra.base_port(0)))

    # reset to origin_cmd only
    if max_gas_wanted is None:
        return

    cli = mantra.cosmos_cli()
    w3 = mantra.w3
    block_gas_limit = 81500000
    tx_gas_limit = 80000000
    max_tx_in_block = block_gas_limit // min(max_gas_wanted, tx_gas_limit)
    print("max_tx_in_block", max_tx_in_block)
    to = ADDRS["validator"]
    params = {"gas": tx_gas_limit}
    _, sended_hash_set = send_txs(w3, cli, to, list(KEYS.values())[0:4], params)
    block_nums = [
        w3.eth.wait_for_transaction_receipt(h).blockNumber for h in sended_hash_set
    ]
    block_nums.sort()
    print(f"all block numbers: {block_nums}")
    # the transactions should be included according to max_gas_wanted
    if max_tx_in_block == 1:
        for block_num, next_block_num in zip(block_nums, block_nums[1:]):
            assert next_block_num == block_num + 1 or next_block_num == block_num + 2
    else:
        for num in block_nums[1:max_tx_in_block]:
            assert num == block_nums[0]
        for num in block_nums[max_tx_in_block:]:
            assert num == block_nums[0] + 1 or num == block_nums[0] + 2

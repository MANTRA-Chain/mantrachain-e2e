// Chain shape for test_mempool_starvation.py, tuned so a pre-fix recheck pool starves:
// - single validator: the flood hits one node, other proposers would build empty
//   blocks regardless of the mempool and mask the signal
// - timeout_commit 20ms: every block cancels the in-flight recheck pass
// - pending-tx-proposal-timeout 2ms: refill window far below the 200-tx gas cap,
//   emulating the slow-hardware ratio of the report on fast hardware
local default = import 'default.jsonnet';
local chain = (import 'chains.jsonnet')[std.extVar('CHAIN_CONFIG')];
local constant = import 'constant.jsonnet';

default {
  'mantra-canary-net-1'+: {
    validators: [{
      'coin-type': 60,
      coins: constant.coins + chain.evm_denom,
      staked: constant.staked + chain.evm_denom,
      gas_prices: constant.gas_price + chain.evm_denom,
      mnemonic: '${VALIDATOR1_MNEMONIC}',
    }],
    config+: {
      consensus+: {
        timeout_commit: '20ms',
      },
      rpc+: {
        // allow ~2000 concurrent broadcast_tx_sync connections
        max_open_connections: 4000,
      },
    },
    'app-config'+: {
      mempool+: {
        // large cap so the flood can build a deep backlog in the app pool
        'max-txs': 50000,
      },
      evm+: {
        mempool+: {
          'pending-tx-proposal-timeout': '2ms',
        },
      },
    },
    genesis+: {
      consensus+: {
        params+: {
          block+: {
            max_gas: '40000000',  // 200 bank sends per block at 200k gas
          },
        },
      },
      app_state+: {
        // The flood is pre-signed with a fixed gas price, so a base fee drifting
        // up as blocks fill would reject later txs mid-flood (seen on
        // mantrachaind). Disabled, a tiny fixed fee stays valid on any chain.
        feemarket+: {
          params+: {
            no_base_fee: true,
            base_fee: '0.000000000000000000',
            min_gas_price: '0.000000000000000000',
          },
        },
      },
    },
  },
}

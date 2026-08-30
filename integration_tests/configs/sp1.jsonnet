local config = import 'default.jsonnet';
local chain = (import 'chains.jsonnet')[std.extVar('CHAIN_CONFIG')];
local evm_mempool = import 'evm_mempool.jsonnet';

config {
  'mantra-canary-net-1'+: evm_mempool(chain) {
    genesis+: {
      app_state+: {
        staking+: {
          params+: {
            unbonding_time: '1814400s',
          },
        },
      },
    },
  },
}

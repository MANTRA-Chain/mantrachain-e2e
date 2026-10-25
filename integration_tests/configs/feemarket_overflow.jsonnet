local config = import 'default.jsonnet';
local chain = (import 'chains.jsonnet')[std.extVar('CHAIN_CONFIG')];
local evm_mempool = import 'evm_mempool.jsonnet';

config {
  'mantra-canary-net-1'+: evm_mempool(chain) {
    genesis+: {
      consensus+: {
        params+: {
          block+: {
            max_gas: '-1',
          },
        },
      },
      app_state+: {
        feemarket+: {
          params+: {
            base_fee: '1',
            min_gas_price: '0',
          },
        },
      },
    },
  },
}

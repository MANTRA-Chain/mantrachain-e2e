local config = import 'default.jsonnet';

config {
  'mantra-canary-net-1'+: {
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

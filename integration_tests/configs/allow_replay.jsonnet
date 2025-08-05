local config = import 'default.jsonnet';

config {
  'mantra-canary-net-1'+: {
    'app-config'+: {
      'json-rpc'+: {
        'allow-unprotected-txs': true,
      },
    },
    genesis+: {
      app_state+: {
        evm+: {
          params+: {
            allow_unprotected_txs: true,
          },
        },
      },
    },
  },
}

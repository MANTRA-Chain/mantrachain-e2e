local config = import 'default.jsonnet';

config {
  'mantra-canary-net-1'+: {
    genesis+: {
      app_state+: {
        evm+: {
          params+: {
            active_static_precompiles: config['mantra-canary-net-1'].genesis.app_state.evm.params.active_static_precompiles + [
              '0x0000000000000000000000000000000000000A00',
            ],
          },
        },
      },
    },
  },
}

local config = import 'default.jsonnet';

config {
  'mantra-canary-net-1'+: {
    genesis+: {
      app_state+: {
        evm+: {
          params+: {
            extended_denom_options:: super.params.extended_denom_options,
          },
        },
      },
    },
  },
}

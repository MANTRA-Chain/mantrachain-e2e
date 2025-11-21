local config = import 'default.jsonnet';

config {
  'mantra-canary-net-1'+: {
    genesis+: {
      app_state+: {
        mint+: {
          params+: {
            max_supply: '700500000000000000000',
          },
        },
      },
    },
  },
}

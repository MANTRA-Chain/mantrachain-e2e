local config = import 'default.jsonnet';

config {
  'mantra-canary-net-1'+: {
    genesis+: {
      app_state+: {
        mint+: {
          params+: {
            inflation_rate_change: '0.9',
            inflation_max: '0.9',
            inflation_min: '0.9',
            blocks_per_year: '300',
          },
        },
      },
    },
  },
}

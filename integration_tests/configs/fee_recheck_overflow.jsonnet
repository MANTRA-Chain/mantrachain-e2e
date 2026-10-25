local config = import 'feemarket_overflow.jsonnet';

// small blocks a flood can fill, starving a low-priority tx while the base fee
// climbs
config {
  'mantra-canary-net-1'+: {
    genesis+: {
      consensus+: {
        params+: {
          block+: {
            max_gas: '400000',
          },
        },
      },
    },
  },
}

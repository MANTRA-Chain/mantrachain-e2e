local config = import 'staking.jsonnet';

config {
  'mantra-canary-net-1'+: {
    genesis+: {
      app_state+: {
        slashing+: {
          params+: {
            // small window + non-zero fraction: jail fast, real ValidatorSlashEvent.
            signed_blocks_window: '30',
            min_signed_per_window: '0.500000000000000000',
            slash_fraction_downtime: '0.010000000000000000',
            downtime_jail_duration: '60s',
          },
        },
      },
    },
  },
}

// 4 validators + aggressive slashing for the v8.1.1 silent-slash repair test.
local config = import 'cosmovisor_recent.jsonnet';
local legacy_evm_denom = 'uom';

config {
  'mantra-canary-net-1'+: {
    validators: [
      {
        'coin-type': 60,
        coins: '100000000000000' + legacy_evm_denom,
        staked: '10000000000000' + legacy_evm_denom,
        gas_prices: '0.01' + legacy_evm_denom,
        mnemonic: '${VALIDATOR' + (i + 1) + '_MNEMONIC}',
      }
      for i in std.range(0, 3)
    ],
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

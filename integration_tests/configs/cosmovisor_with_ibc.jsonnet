local ibc = import 'ibc_evmd.jsonnet';

// Same v8.3.0 genesis binary as cosmovisor.jsonnet, paired with an evmd chain so
// the upgrades run while an IBC channel is live.
ibc {
  'mantra-canary-net-1'+: {
    'app-config'+: {
      evm+: {
        'evm-chain-id': 5887,
      },
    },
    genesis+: {
      consensus_params: {
        block: {
          max_bytes: '3000000',
          max_gas: '300000000',
        },
      },
      app_state+: {
        gov+: {
          params+: {
            // long enough for every validator's vote to land, short enough (in
            // blocks) to close before submit+WAIT_HEIGHT or the upgrade
            // schedules in the past; slower IBC blocks
            voting_period: '8s',
            max_deposit_period: '8s',
          },
        },
      },
    },
  },
}

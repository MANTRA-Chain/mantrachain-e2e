local config = import 'default.jsonnet';

// Opt out of the app-side EVM mempool: with max-txs < 0 the node installs the
// no-op sdk mempool, so comet has to run its own flood mempool, and json-rpc
// refuses to start without the EVM mempool. The evm start command force-sets
// --mempool.max-txs, shadowing the app.toml value, so only the start flag
// takes effect; the app-config entry is kept for readers.
config {
  'mantra-canary-net-1'+: {
    'start-flags': '--trace --mempool.max-txs=-1',
    config+: {
      mempool+: {
        type: 'flood',
      },
    },
    'app-config'+: {
      'json-rpc'+: {
        enable: false,
      },
      mempool+: {
        'max-txs': -1,
      },
    },
  },
}

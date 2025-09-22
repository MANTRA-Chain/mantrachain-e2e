local config = import 'default.jsonnet';
local chain_id = 'mantra_9001-1';

config {
  'mantra-canary-net-1'+: {
    client_config+: {
      'chain-id': chain_id,
    },
    genesis+: {
      chain_id+: chain_id,
    },
    'app-config'+: {
      evm+: {
        'evm-chain-id': 9001,
      },
    },
  },
}

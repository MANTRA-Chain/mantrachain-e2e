local config = import 'default.jsonnet';
local chain = (import 'chains.jsonnet')[std.extVar('CHAIN_CONFIG')];

config {
  'mantra-canary-net-1'+: {
    validators: [validator {
      'coin-type':: validator['coin-type'],
      'app-config'+: {
        mempool: {
          'max-txs': -1,
        },
      },
    } for validator in super.validators],
  },
}

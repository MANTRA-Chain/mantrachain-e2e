local config = import 'default.jsonnet';
local chain = (import 'chains.jsonnet')[std.extVar('CHAIN_CONFIG')];
local constant = import 'constant.jsonnet';
local coin_type = if std.objectHas(chain, 'coin-type') && chain['coin-type'] != null then chain['coin-type'] else 60;

config {
  'mantra-canary-net-1'+: {
    validators+: [{
      'coin-type': coin_type,
      coins: constant.coins + chain.evm_denom,
      staked: constant.staked + chain.evm_denom,
      gas_prices: constant.gas_price + chain.evm_denom,
      mnemonic: '${VALIDATOR4_MNEMONIC}',
      config: {
        db_backend: 'pebbledb',
      },
      'app-config': {
        'app-db-backend': 'pebbledb',
        pruning: 'everything',
        'state-sync': {
          'snapshot-interval': 0,
        },
        // Reads must reach disk. With the default cache a pruned node is
        // still in memory and the write succeeds, which is why a damaged node
        // can run for weeks and only fault after a restart.
        'iavl-cache-size': 0,
      },
    }],
  },
}

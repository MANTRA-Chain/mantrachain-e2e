// node3, tuned so a stale version-pinned context faults on a pruned node
local config = import 'default.jsonnet';
local chain = (import 'chains.jsonnet')[std.extVar('CHAIN_CONFIG')];
local constant = import 'constant.jsonnet';
local coin_type = if std.objectHas(chain, 'coin-type') && chain['coin-type'] != null then chain['coin-type'] else 60;
local chain = (import 'chains.jsonnet')[std.extVar('CHAIN_CONFIG')];
local evm_mempool = import 'evm_mempool.jsonnet';

config {
  'mantra-canary-net-1'+: evm_mempool(chain) {
    'app-config'+: {
      mempool+: {
        'max-txs': 0,
      },
    },
    validators+: [{
      'coin-type': coin_type,
      coins: constant.coins + chain.evm_denom,
      staked: constant.staked + chain.evm_denom,
      gas_prices: constant.gas_price + chain.evm_denom,
      mnemonic: '${VALIDATOR4_MNEMONIC}',
      'app-config'+: {
        // Prune close behind the tip so a stale pin falls outside the window
        // quickly. Not the floor of 2: with the fix EndBlock re-pins every
        // block, leaving the pin a few blocks back, and at 2 even that is
        // already prunable -- the test would fault either way and prove
        // nothing. 20 is above the fixed drift and far below a frozen pin's.
        pruning: 'custom',
        'pruning-keep-recent': '20',
        'pruning-interval': '10',
        // Snapshots cap pruning at pruneSnapshotHeights[0] + interval - 1
        // (store/pruning/manager.go), disabling it in practice.
        'state-sync'+: {
          'snapshot-interval': 0,
        },
        // Reads must reach disk: at the default 781250 the whole local tree
        // fits in iavl's cache, so pruned nodes still answer from RAM.
        'iavl-cache-size': 0,
        // Otherwise Get() is answered from the fast-node index and never walks
        // the tree, so a pruned node is never visited.
        'iavl-disable-fastnode': true,
      },
    }],
  },
}

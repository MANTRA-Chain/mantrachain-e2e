// indexer x mempool matrix for test_receipt_retry.py; mempool off is max-txs=-1,
// also as a start flag since cosmos/evm's forced --mempool.max-txs=0 shadows app.toml
local config = import 'default.jsonnet';
local chain = (import 'chains.jsonnet')[std.extVar('CHAIN_CONFIG')];
local evm_mempool = import 'evm_mempool.jsonnet';

function(indexer, mempool)
  config {
    'mantra-canary-net-1'+: (if mempool then evm_mempool(chain) else {}) {
      validators: [config['mantra-canary-net-1'].validators[0]],
      'start-flags': config['mantra-canary-net-1']['start-flags']
                     + (if mempool then '' else ' --mempool.max-txs=-1'),
      config+: {
        tx_index+: {
          indexer: if indexer then 'null' else 'kv',
        },
        mempool+: {
          type: if mempool && chain.cmd == 'evmd' then 'app' else 'flood',
        },
      },
      'app-config'+: {
        'json-rpc'+: {
          'enable-indexer': indexer,
        },
        mempool+: {
          'max-txs': if mempool then 5000 else -1,
        },
      },
    },
  }

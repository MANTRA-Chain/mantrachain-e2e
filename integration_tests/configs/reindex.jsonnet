local config = import 'enable-indexer.jsonnet';

// unlike enable-indexer.jsonnet this keeps comet's tx_index, so the same node
// can serve receipts from either source
config {
  'mantra-canary-net-1'+: {
    config+: {
      tx_index+: {
        indexer: 'kv',
      },
    },
  },
}

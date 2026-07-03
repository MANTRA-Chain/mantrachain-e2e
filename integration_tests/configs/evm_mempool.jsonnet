// evmd needs comet-bft mempool.type 'app'; other binaries keep flood.
function(chain) if chain.cmd == 'evmd' then {
  config+: {
    mempool+: {
      type+: 'app',
    },
  },
  'app-config'+: {
    evm+: {
      mempool: {
        'operate-exclusively': true,
      },
    },
  },
} else {}

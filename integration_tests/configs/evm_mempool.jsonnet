// EVM binaries hand the mempool to the app (paired with app-config
// mempool.max-txs, which must stay enabled). The rest spell out 'flood' rather
// than opt out, to override the 'app' they inherit from ``basic``.
local flood_cmds = [
  'simd',  // no EVM mempool
  'nvnmchaind',  // cosmos/evm too old for the app mempool
];

function(chain) {
  config+: {
    mempool+: {
      type: if std.member(flood_cmds, chain.cmd) then 'flood' else 'app',
    },
  },
}

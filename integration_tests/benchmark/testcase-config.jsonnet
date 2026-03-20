local chains = import '../configs/chains.jsonnet';
local chain = chains[std.extVar('CHAIN_CONFIG')];

local extended_denom =
  if std.objectHas(chain, 'evm') &&
     std.objectHas(chain.evm, 'params') &&
     std.objectHas(chain.evm.params, 'extended_denom_options') &&
     std.objectHas(chain.evm.params.extended_denom_options, 'extended_denom')
  then chain.evm.params.extended_denom_options.extended_denom
  else chain.evm_denom;

{
  binary: chain.cmd,
  image_name: chain.cmd + '-testground',
  address_prefix: chain['account-prefix'],
  chain_id: chain.chain_id,
  evm_denom: chain.evm_denom,
  extended_denom: extended_denom,
  evm_chain_id: chain.evm_chain_id,
  outdir: '/tmp/data/out',
  validators: 1,
  fullnodes: 0,
  validator_generate_load: true,
  num_accounts: 800,
  num_txs: 20,
  tx_type: 'simple-transfer',
  app_patch: {
    'json-rpc': { enable: true },
    mempool: { 'max-txs': -1 },
  },
  config_patch: {
    mempool: { size: 50000, type: 'app' },
    consensus: { timeout_commit: '20ms' },
  },
  genesis_patch: {
    consensus: { params: { block: { max_gas: '363000000' } } },
    app_state: {
      bank: chain.bank,
      evm: chain.evm,
    },
  },
}

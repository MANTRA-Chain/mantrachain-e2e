local config = import 'default.jsonnet';
local chain = (import 'chains.jsonnet')[std.extVar('CHAIN_CONFIG')];
local constant = import 'constant.jsonnet';

config {
  'mantra-canary-net-1'+: {
    validators: super.validators + [{
      'coin-type': 60,
      coins: constant.coins + chain.evm_denom,
      staked: constant.staked + chain.evm_denom,
      gas_prices: constant.gas_price + chain.evm_denom,
      min_self_delegation: constant.min_self_delegation,
      mnemonic: '${VALIDATOR4_MNEMONIC}',
    }],
  },
}

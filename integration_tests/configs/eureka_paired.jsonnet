// Two mantra-binary instances for cross-chain Eureka (IBC v2) tests.
// Distinct ``evm-chain-id`` per chain for EIP-155 replay protection.
// No Hermes wiring — Eureka uses IBC clients directly.

local config = import 'default.jsonnet';
local chain = (import 'chains.jsonnet')[std.extVar('CHAIN_CONFIG')];
local basic = config['mantra-canary-net-1'];
local constant = import 'constant.jsonnet';
local coins = constant.coins;

config {
  // need ``key_name`` for pystarport's multi-chain init (defaults to relayer)
  'mantra-canary-net-1'+: {
    key_name: 'signer2',
  },
  'mantra-canary-net-2': basic {
    key_name: 'signer1',
    'app-config'+: {
      evm+: {
        'evm-chain-id': chain.evm_chain_id + 1,
      },
    },
    validators: [
      validator {
        base_port: 26800 + i * 10,
        coins: coins + chain.evm_denom,
      }
      for i in std.range(0, std.length(super.validators) - 1)
      for validator in [super.validators[i]]
    ],
  },
}

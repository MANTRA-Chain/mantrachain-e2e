local config = import 'default.jsonnet';
local rly_chain = import 'rly_chain.jsonnet';
local rly_common = import 'rly_common.jsonnet';
local chain = (import 'chains.jsonnet')[std.extVar('CHAIN_CONFIG')];
local basic = config['mantra-canary-net-1'];
local ibc_common = import 'ibc_common.jsonnet';

config {
  'mantra-canary-net-1'+: ibc_common {
    key_name: 'signer2',
    'account-prefix': chain['account-prefix'],
  },
  'mantra-canary-net-2'+: basic + ibc_common {
    key_name: 'signer1',
    'account-prefix': chain['account-prefix'],
    validators: std.mapWithIndex(function(i, validator) validator {
      base_port: 26800 + i * 10,
    }, super.validators),
  },
  relayer: rly_common {
    chains: [
      rly_chain {
        id: 'mantra-canary-net-1',
        gas_price+: {
          denom: chain.evm_denom,
        },
      },
      rly_chain {
        id: 'mantra-canary-net-2',
        gas_price+: {
          denom: chain.evm_denom,
        },
      },
    ],
  },
}

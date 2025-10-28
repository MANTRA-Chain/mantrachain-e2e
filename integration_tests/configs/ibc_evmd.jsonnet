local config = import 'default.jsonnet';
local rly_chain = import 'rly_chain.jsonnet';
local rly_common = import 'rly_common.jsonnet';
local chain = (import 'chains.jsonnet')[std.extVar('CHAIN_CONFIG')];
local basic = config['mantra-canary-net-1'];
local ibc_common = import 'ibc_common.jsonnet';
local evmd_chain = (import 'chains.jsonnet').evmd;

config {
  'mantra-canary-net-1'+: ibc_common {
    key_name: 'signer2',
    'account-prefix': chain['account-prefix'],
  },
  'evm-canary-net-1': basic + ibc_common {
    key_name: 'signer1',
    'account-prefix': evmd_chain['account-prefix'],
    accounts: [account {
      coins: '100000000000000000000' + evmd_chain.evm_denom,
    } for i in std.range(0, std.length(super.accounts) - 1) for account in [super.accounts[i]]],
    'app-config'+: {
      evm+: {
        'evm-chain-id': evmd_chain.evm_chain_id,
      },
      'minimum-gas-prices': '0' + evmd_chain.evm_denom,
    },
    cmd: evmd_chain.cmd,
    genesis+: {
      app_state+: {
        bank+: {
          denom_metadata: evmd_chain.bank.denom_metadata,
        },
        crisis+: {
          constant_fee: {
            denom: evmd_chain.evm_denom,
          },
        },
        evm+: {
          params+: {
            evm_denom: evmd_chain.evm_denom,
            extended_denom_options+: {
              extended_denom: evmd_chain.evm_denom,
            },
          },
        },
        erc20: {},
        gov+: {
          params+: {
            expedited_min_deposit: [
              {
                amount: '2',
                denom: evmd_chain.evm_denom,
              },
            ],
            min_deposit: [{
              denom: evmd_chain.evm_denom,
              amount: '1',
            }],
          },
        },
        mint+: {
          params+: {
            mint_denom: evmd_chain.evm_denom,
          },
        },
        staking+: {
          params+: {
            bond_denom: evmd_chain.evm_denom,
          },
        },
      },
    },
    validators: [validator {
      base_port: 26800 + i * 10,
      coins: '100000000000000000000' + evmd_chain.evm_denom,
      gas_prices: '0.01' + evmd_chain.evm_denom,
      staked: '10000000000000000000' + evmd_chain.evm_denom,
    } for i in std.range(0, std.length(super.validators) - 1) for validator in [super.validators[i]]],
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
        id: 'evm-canary-net-1',
        gas_price+: {
          denom: evmd_chain.evm_denom,
        },
      },
    ],
  },
}

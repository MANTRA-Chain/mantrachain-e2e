local config = import 'default.jsonnet';
local rly_chain = import 'rly_chain.jsonnet';
local rly_common = import 'rly_common.jsonnet';
local chain = (import 'chains.jsonnet')[std.extVar('CHAIN_CONFIG')];
local basic = config['mantra-canary-net-1'];
local ibc_common = import 'ibc_common.jsonnet';
local inveniamd_chain = (import 'chains.jsonnet').inveniamd;

config {
  'mantra-canary-net-1'+: ibc_common {
    key_name: 'signer2',
    'account-prefix': chain['account-prefix'],
    genesis+: {
      app_state+: {
        provider+: {
          params+: {
            blocks_per_epoch: 5,
            number_of_epochs_to_start_receiving_rewards: 2,
          },
        },
      },
    },
  },
  'inveniam-canary-net-1': basic + ibc_common {
    key_name: 'signer1',
    'account-prefix': inveniamd_chain['account-prefix'],
    accounts: [account {
      coins: '100000000000000000000' + inveniamd_chain.evm_denom,
    } for i in std.range(0, std.length(super.accounts) - 1) for account in [super.accounts[i]]],
    'app-config'+: {
      evm+: {
        'evm-chain-id': inveniamd_chain.evm_chain_id,
      },
      'minimum-gas-prices': '0' + inveniamd_chain.evm_denom,
    },
    cmd: inveniamd_chain.cmd,
    genesis+: {
      app_state+: {
        bank+: {
          denom_metadata: inveniamd_chain.bank.denom_metadata,
        },
        crisis+: {
          constant_fee: {
            denom: inveniamd_chain.evm_denom,
          },
        },
        evm+: {
          params+: {
            evm_denom: inveniamd_chain.evm_denom,
            extended_denom_options+: {
              extended_denom: inveniamd_chain.evm_denom,
            },
            active_static_precompiles: basic.genesis.app_state.evm.params.active_static_precompiles + inveniamd_chain.evm.params.active_static_precompiles,
          },
        },
        erc20: {},
        gov+: {
          params+: {
            expedited_min_deposit: [
              {
                amount: '2',
                denom: inveniamd_chain.evm_denom,
              },
            ],
            min_deposit: [{
              denom: inveniamd_chain.evm_denom,
              amount: '1',
            }],
          },
        },
        mint+: {
          params+: {
            mint_denom: inveniamd_chain.evm_denom,
          },
        },
        staking+: {
          params+: {
            bond_denom: inveniamd_chain.evm_denom,
          },
        },
      },
    },
    validators: [validator {
      base_port: 26800 + i * 10,
      coins: '100000000000000000000' + inveniamd_chain.evm_denom,
      gas_prices: '0.01' + inveniamd_chain.evm_denom,
      staked:: validator.staked,
      autostart: 'false',
    } for i in std.range(0, std.length(super.validators) - 1) for validator in [super.validators[i]]],
  },
  relayer: rly_common {
    chains: [
      rly_chain {
        id: 'mantra-canary-net-1',
        ccv_consumer_chain: false,
        gas_price+: {
          denom: chain.evm_denom,
        },
      },
      rly_chain {
        id: 'inveniam-canary-net-1',
        ccv_consumer_chain: true,
        gas_price+: {
          price: 10000000000,
          denom: inveniamd_chain.evm_denom,
        },
      },
    ],
  },
}

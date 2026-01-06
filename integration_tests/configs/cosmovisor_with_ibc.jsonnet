local ibc = import 'ibc_evmd.jsonnet';
local legacy_evm_denom = 'uom';
local constant = import 'constant.jsonnet';
local gas_price = constant.gas_price;
local coins = constant.coins;
local staked = constant.staked;

ibc {
  'mantra-canary-net-1'+: {
    'app-config'+: {
      evm+: {
        'evm-chain-id': 5887,
      },
      'minimum-gas-prices': '0' + legacy_evm_denom,
    },
    validators: [validator {
      'coin-type':: validator['coin-type'],
      coins: coins + legacy_evm_denom,
      staked: staked + legacy_evm_denom,
      gas_prices: gas_price + legacy_evm_denom,
      'app-config'+: {
        mempool: {
          'max-txs': -1,  // TODO: wait fix sender release
        },
      },
    } for validator in super.validators],
    accounts: [account {
      'coin-type':: account['coin-type'],
      coins: coins + legacy_evm_denom,
    } for account in super.accounts],
    genesis+: {
      consensus_params: {
        block: {
          max_bytes: '3000000',
          max_gas: '300000000',
        },
      },
      app_state+: {
        bank+: {
          denom_metadata: [{
            description: 'The native staking token of the Mantrachain.',
            denom_units: [
              {
                denom: legacy_evm_denom,
              },
              {
                denom: 'om',
                exponent: 6,
              },
            ],
            base: legacy_evm_denom,
            display: 'om',
            name: 'om',
            symbol: 'OM',
          }],
        },
        crisis+: {
          constant_fee+: {
            denom: legacy_evm_denom,
          },
        },
        mint+: {
          params+: {
            mint_denom: legacy_evm_denom,
          },
        },
        staking+: {
          params+: {
            bond_denom: legacy_evm_denom,
          },
        },
        gov+: {
          params+: {
            expedited_min_deposit: [
              {
                amount: '2',
                denom: legacy_evm_denom,
              },
            ],
            min_deposit: [
              {
                amount: '1',
                denom: legacy_evm_denom,
              },
            ],
          },
        },
        erc20+: {
          token_pairs: [
            {
              contract_owner: 1,
              denom: legacy_evm_denom,
              enabled: true,
              erc20_address: '0x4200000000000000000000000000000000000006',
            },
          ],
        },
        evm+: {
          params+: {
            evm_denom: legacy_evm_denom,
            extended_denom_options: {
              extended_denom: 'aom',
            },
          },
        },
        feemarket: {
          params: {
            base_fee: '0.010000000000000000',
            min_gas_price: '0.010000000000000000',
          },
        },
      },
    },
  },
  relayer+: {
    chains: [
      super.chains[0] {
        gas_price+: {
          denom: legacy_evm_denom,
          price: 0.1,
        },
      },
    ] + super.chains[1:],
  },
}

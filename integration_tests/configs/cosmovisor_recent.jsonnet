local config = import 'fullnode.jsonnet';
local legacy_evm_denom = 'uom';

config {
  'mantra-canary-net-1'+: {
    'app-config'+: {
      'minimum-gas-prices': '0' + legacy_evm_denom,
    },
    config+: {
      consensus+: {
        timeout_commit: '100ms',
      },
    },
    validators: [
      if i == 0 then
        validator {
          'coin-type':: validator['coin-type'],
          coins: '100000000000000000000' + legacy_evm_denom,
          staked: '10000000000000000000' + legacy_evm_denom,
          gas_prices: '0.01' + legacy_evm_denom,
        }
      else
        validator {
          'coin-type':: validator['coin-type'],
          coins: '100000000000000000000' + legacy_evm_denom,
          gas_prices: '0.01' + legacy_evm_denom,
        }
      for i in std.range(0, std.length(super.validators) - 1)
      for validator in [super.validators[i]]
    ],
    accounts: [account {
      'coin-type':: account['coin-type'],
      coins: '100000000000000000000' + legacy_evm_denom,
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
}

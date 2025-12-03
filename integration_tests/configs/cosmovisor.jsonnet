local config = import 'default.jsonnet';
local legacy_evm_denom = 'uom';

config {
  'mantra-canary-net-1'+: {
    'app-config'+: {
      evm+: {
        'evm-chain-id': 5887,
      },
      'minimum-gas-prices': '0' + legacy_evm_denom,
    },
    validators: [validator {
      'coin-type':: validator['coin-type'],
      coins: '100000000000000000000' + legacy_evm_denom,
      staked: '10000000000000000000' + legacy_evm_denom,
      gas_prices: '0.01' + legacy_evm_denom,
      'app-config'+: {
        mempool: {
          'max-txs': -1,  // TODO: wait fix sender release
        },
      },
    } for validator in super.validators],
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
        oracle+: {
          currency_pair_genesis: [
            {
              currency_pair: {
                Base: 'OM',
                Quote: 'USD',
              },
              nonce: 0,
              id: 1,
            },
            {
              currency_pair: {
                Base: 'USD',
                Quote: 'OM',
              },
              nonce: 0,
              id: 2,
            },
          ],
          next_id: 3,
        },
        bank+: {
          denom_metadata:: super.bank.denom_metadata,
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
        evm:: super.evm,
        erc20:: super.erc20,
        feemarket: {
          params: {
            alpha: '0.000000000000000000',
            beta: '1.000000000000000000',
            gamma: '0.000000000000000000',
            delta: '0.000000000000000000',
            min_base_gas_price: '0.010000000000000000',
            min_learning_rate: '0.125000000000000000',
            max_learning_rate: '0.125000000000000000',
            max_block_utilization: '75000000',
            window: '1',
            fee_denom: legacy_evm_denom,
            enabled: true,
            distribute_fees: false,
          },
        },
      },
    },
  },
}

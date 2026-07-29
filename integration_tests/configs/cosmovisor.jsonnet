local config = import 'default.jsonnet';
local constant = import 'constant.jsonnet';
local coins = constant.coins;
local staked = constant.staked;
local legacy_evm_denom = 'uom';
local coin_type = config['mantra-canary-net-1'].validators[0]['coin-type'];

// Merged upgrade genesis: starts from the v6.1.3 genesis binary and upgrades
// through v7.0.0 -> v8.x. Topology is 2 validators (node0, node1) + 1
// non-validating fullnode (node2). node2 is frozen at pre-v7 state and reused
// as a grpc-only archive node for the historical-query checks, so it must not
// count towards consensus (2 validators keep producing while it is offline).
config {
  'mantra-canary-net-1'+: {
    'app-config'+: {
      'minimum-gas-prices': '0' + legacy_evm_denom,
    },
    config+: {
      consensus+: {
        timeout_commit: '500ms',
      },
    },
    validators: [validator {
      'coin-type':: validator['coin-type'],
      coins: coins + legacy_evm_denom,
      staked: staked + legacy_evm_denom,
      gas_prices: '0.01' + legacy_evm_denom,
    } for validator in super.validators[0:2]] + [{
      name: 'fullnode',
      'coin-type': coin_type,
      coins: coins + legacy_evm_denom,
      gas_prices: '0.01' + legacy_evm_denom,
      'app-config'+: {
        'json-rpc': {
          enable: false,
        },
      },
    }],
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

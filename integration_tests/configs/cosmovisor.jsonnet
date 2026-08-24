local config = import 'default.jsonnet';
local chain = (import 'chains.jsonnet')[std.extVar('CHAIN_CONFIG')];
local constant = import 'constant.jsonnet';
local coins = constant.coins;
local coin_type = config['mantra-canary-net-1'].validators[0]['coin-type'];

// Merged upgrade genesis: starts from the v8.3.0 genesis binary and upgrades
// through the rest of v8.x. Topology is 2 validators (node0, node1) + 1
// non-validating fullnode (node2). node2 is frozen at an early height and reused
// as a grpc-only archive node for the historical-query checks, so it must not
// count towards consensus (2 validators keep producing while it is offline).
config {
  'mantra-canary-net-1'+: {
    config+: {
      mempool+: {
        // genesis binary predates the app-side mempool; ensure_comet_mempool_app
        // flips this back to 'app' before the v8.5.0 upgrade
        type: 'flood',
      },
      consensus+: {
        timeout_commit: '500ms',
      },
    },
    // hidden ``coin-type`` keeps pystarport from passing --coin-type, which the
    // genesis binary does not accept; its built-in default is the same 60
    validators: [validator {
      'coin-type':: validator['coin-type'],
    } for validator in super.validators[0:2]] + [{
      name: 'fullnode',
      'coin-type': coin_type,
      coins: coins + chain.evm_denom,
      gas_prices: constant.gas_price + chain.evm_denom,
      'app-config'+: {
        'json-rpc': {
          enable: false,
        },
      },
    }],
    accounts: [account {
      'coin-type':: account['coin-type'],
    } for account in super.accounts],
    genesis+: {
      consensus_params: {
        block: {
          max_bytes: '3000000',
          max_gas: '300000000',
        },
      },
      app_state+: {
        gov+: {
          params+: {
            // long enough for every validator's vote to land, short enough (in
            // blocks) to close before submit+WAIT_HEIGHT or the upgrade
            // schedules in the past; fast blocks here
            voting_period: '6s',
            max_deposit_period: '6s',
          },
        },
        // the v8.5.0 handler checks the fee denom's display unit is at
        // exponent 18 before enabling virtual fee collection, and DeductFees
        // walks the same metadata afterwards; seed it for both to read
        bank+: {
          denom_metadata: [{
            description: 'The native token of MANTRA Chain',
            denom_units: [
              { denom: chain.evm_denom, exponent: 0 },
              { denom: 'mantra', exponent: 18 },
            ],
            base: chain.evm_denom,
            display: 'mantra',
            name: 'MANTRA',
            symbol: 'OM',
          }],
        },
        // the v8.0.0 upgrade handler seeded these; starting past it they have to
        // come from genesis instead (see verify_provider)
        provider+: {
          params+: {
            blocks_per_epoch: 10,
            number_of_epochs_to_start_receiving_rewards: 2,
            consumer_reward_denom_registration_fee: {
              denom: chain.evm_denom,
              amount: '4000000000000000000',
            },
          },
        },
      },
    },
  },
}

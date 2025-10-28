{
  dotenv: '../../scripts/.env',
  'mantra-canary-net-1': {
    'account-prefix': 'mantra',
    accounts: [
      {
        'coin-type': 60,
        coins: '100000000000000000000uom,1000000000000atoken',
        mnemonic: '${COMMUNITY_MNEMONIC}',
        name: 'community',
      },
      {
        'coin-type': 60,
        coins: '100000000000000000000uom',
        mnemonic: '${SIGNER1_MNEMONIC}',
        name: 'signer1',
      },
      {
        'coin-type': 60,
        coins: '100000000000000000000uom',
        mnemonic: '${SIGNER2_MNEMONIC}',
        name: 'signer2',
      },
      {
        'coin-type': 60,
        coins: '100000000000000000000uom',
        mnemonic: '${RESERVE_MNEMONIC}',
        name: 'reserve',
        vesting: '60s',
      },
    ],
    'app-config': {
      evm: {
        'evm-chain-id': 7888,
      },
      grpc: {
        'skip-check-header': true,
      },
      'iavl-lazy-loading': true,
      'index-events': [
        'ethereum_tx.ethereumTxHash',
        'message.action',
      ],
      'json-rpc': {
        address: '127.0.0.1:{EVMRPC_PORT}',
        'allow-unprotected-txs': true,
        api: 'eth,net,web3,debug,txpool',
        'block-range-cap': 10000,
        enable: true,
        'feehistory-cap': 100,
        'gas-cap': 30000000,
        'logs-cap': 10000,
        'ws-address': '127.0.0.1:{EVMRPC_PORT_WS}',
      },
      mempool: {
        'max-txs': 5000,
      },
      'minimum-gas-prices': '0uom',
    },
    cmd: 'mantrachaind',
    'coin-type': 60,
    config: {
      mempool: {
        version: 'v1',
      },
    },
    genesis: {
      app_state: {
        bank: {
          denom_metadata: [
            {
              base: 'uom',
              denom_units: [
                {
                  denom: 'uom',
                },
                {
                  denom: 'om',
                  exponent: 6,
                },
              ],
              description: 'The native staking token of the Mantrachain.',
              display: 'om',
              name: 'om',
              symbol: 'OM',
            },
            {
              base: 'atoken',
              denom_units: [
                {
                  denom: 'atoken',
                  exponent: 0,
                },
                {
                  denom: 'token',
                  exponent: 18,
                },
              ],
              display: 'token',
              name: 'Test Coin',
              symbol: 'ATOKEN',
            },
          ],
        },
        circuit: {
          disabled_type_urls: [
            '/cosmos.distribution.v1beta1.MsgDepositValidatorRewardsPool',
          ],
        },
        crisis: {
          constant_fee: {
            denom: 'uom',
          },
        },
        erc20: {
          native_precompiles: [
            '0x4200000000000000000000000000000000000006',
          ],
          token_pairs: [
            {
              contract_owner: 1,
              denom: 'uom',
              enabled: true,
              erc20_address: '0x4200000000000000000000000000000000000006',
            },
          ],
        },
        evm: {
          params: {
            active_static_precompiles: [
              '0x0000000000000000000000000000000000000800',
              '0x0000000000000000000000000000000000000801',
              '0x0000000000000000000000000000000000000805',
              '0x0000000000000000000000000000000000000807',
            ],
            evm_denom: 'uom',
            extended_denom_options: {
              extended_denom: 'aom',
            },
          },
        },
        feemarket: {
          params: {
            base_fee: '0',
            min_gas_multiplier: '0',
            min_gas_price: '0',
            no_base_fee: true,
          },
        },
        gov: {
          params: {
            expedited_min_deposit: [
              {
                amount: '2',
                denom: 'uom',
              },
            ],
            expedited_voting_period: '1s',
            max_deposit_period: '10s',
            min_deposit: [
              {
                amount: '1',
                denom: 'uom',
              },
            ],
            voting_period: '10s',
          },
        },
        mint: {
          params: {
            mint_denom: 'uom',
          },
        },
        staking: {
          params: {
            bond_denom: 'uom',
            unbonding_time: '1814400s',
          },
        },
      },
      consensus: {
        params: {
          abci: {
            vote_extensions_enable_height: '1',
          },
          block: {
            max_bytes: '1048576',
            max_gas: '81500000',
          },
        },
      },
    },
    key_name: 'signer2',
    'start-flags': '--trace',
    validators: [
      {
        'coin-type': 60,
        coins: '100000000000000000000uom',
        gas_prices: '0.01uom',
        mnemonic: '${VALIDATOR1_MNEMONIC}',
        staked: '10000000000000000000uom',
      },
      {
        'app-config': {
          'app-db-backend': 'pebbledb',
        },
        'coin-type': 60,
        coins: '100000000000000000000uom',
        config: {
          db_backend: 'pebbledb',
        },
        gas_prices: '0.01uom',
        mnemonic: '${VALIDATOR2_MNEMONIC}',
        staked: '10000000000000000000uom',
      },
      {
        'app-config': {
          'app-db-backend': 'goleveldb',
        },
        'coin-type': 60,
        coins: '100000000000000000000uom',
        config: {
          db_backend: 'goleveldb',
        },
        gas_prices: '0.01uom',
        mnemonic: '${VALIDATOR3_MNEMONIC}',
        staked: '10000000000000000000uom',
      },
    ],
  },
  'evm-canary-net-1': {
    'account-prefix': 'cosmos',
    accounts: [
      {
        'coin-type': 60,
        coins: '100000000000000000000atest,1000000000000atoken',
        mnemonic: '${COMMUNITY_MNEMONIC}',
        name: 'community',
      },
      {
        'coin-type': 60,
        coins: '100000000000000000000atest',
        mnemonic: '${SIGNER1_MNEMONIC}',
        name: 'signer1',
      },
      {
        'coin-type': 60,
        coins: '100000000000000000000atest',
        mnemonic: '${SIGNER2_MNEMONIC}',
        name: 'signer2',
      },
      {
        'coin-type': 60,
        coins: '100000000000000000000atest',
        mnemonic: '${RESERVE_MNEMONIC}',
        name: 'reserve',
        vesting: '60s',
      },
    ],
    'app-config': {
      evm: {
        'evm-chain-id': 262144,
      },
      grpc: {
        'skip-check-header': true,
      },
      'iavl-lazy-loading': true,
      'index-events': [
        'ethereum_tx.ethereumTxHash',
        'message.action',
      ],
      'json-rpc': {
        address: '127.0.0.1:{EVMRPC_PORT}',
        'allow-unprotected-txs': true,
        api: 'eth,net,web3,debug,txpool',
        'block-range-cap': 10000,
        enable: true,
        'feehistory-cap': 100,
        'gas-cap': 30000000,
        'logs-cap': 10000,
        'ws-address': '127.0.0.1:{EVMRPC_PORT_WS}',
      },
      mempool: {
        'max-txs': 5000,
      },
      'minimum-gas-prices': '0atest',
    },
    cmd: 'evmd',
    'coin-type': 60,
    config: {
      mempool: {
        version: 'v1',
      },
    },
    genesis: {
      app_state: {
        bank: {
          denom_metadata: [
            {
              base: 'atest',
              denom_units: [
                {
                  denom: 'atest',
                  exponent: 0,
                },
                {
                  denom: 'test',
                  exponent: 18,
                },
              ],
              description: 'The native staking token.',
              display: 'test',
              name: 'test',
              symbol: 'ATOM',
            },
            {
              base: 'atoken',
              denom_units: [
                {
                  denom: 'atoken',
                  exponent: 0,
                },
                {
                  denom: 'token',
                  exponent: 18,
                },
              ],
              display: 'token',
              name: 'Test Coin',
              symbol: 'ATOKEN',
            },
          ],
        },
        circuit: {
          disabled_type_urls: [
            '/cosmos.distribution.v1beta1.MsgDepositValidatorRewardsPool',
          ],
        },
        crisis: {
          constant_fee: {
            denom: 'atest',
          },
        },
        erc20: {
          native_precompiles: [
            '0x4200000000000000000000000000000000000006',
          ],
          token_pairs: [
            {
              contract_owner: 1,
              denom: 'atest',
              enabled: true,
              erc20_address: '0x4200000000000000000000000000000000000006',
            },
          ],
        },
        evm: {
          params: {
            active_static_precompiles: [
              '0x0000000000000000000000000000000000000800',
              '0x0000000000000000000000000000000000000801',
              '0x0000000000000000000000000000000000000805',
              '0x0000000000000000000000000000000000000807',
            ],
            evm_denom: 'atest',
            extended_denom_options: {
              extended_denom: 'atest',
            },
          },
        },
        feemarket: {
          params: {
            base_fee: '0',
            min_gas_multiplier: '0',
            min_gas_price: '0',
            no_base_fee: true,
          },
        },
        gov: {
          params: {
            expedited_min_deposit: [
              {
                amount: '2',
                denom: 'atest',
              },
            ],
            expedited_voting_period: '1s',
            max_deposit_period: '10s',
            min_deposit: [
              {
                amount: '1',
                denom: 'atest',
              },
            ],
            voting_period: '10s',
          },
        },
        mint: {
          params: {
            mint_denom: 'atest',
          },
        },
        staking: {
          params: {
            bond_denom: 'atest',
            unbonding_time: '1814400s',
          },
        },
      },
      consensus: {
        params: {
          abci: {
            vote_extensions_enable_height: '1',
          },
          block: {
            max_bytes: '1048576',
            max_gas: '81500000',
          },
        },
      },
    },
    key_name: 'signer1',
    'start-flags': '--trace',
    validators: [
      {
        base_port: 26800,
        'coin-type': 60,
        coins: '100000000000000000000atest',
        gas_prices: '0.01atest',
        mnemonic: '${VALIDATOR1_MNEMONIC}',
        staked: '10000000000000000000atest',
      },
      {
        'app-config': {
          'app-db-backend': 'pebbledb',
        },
        base_port: 26810,
        'coin-type': 60,
        coins: '100000000000000000000atest',
        config: {
          db_backend: 'pebbledb',
        },
        gas_prices: '0.01atest',
        mnemonic: '${VALIDATOR2_MNEMONIC}',
        staked: '10000000000000000000atest',
      },
      {
        'app-config': {
          'app-db-backend': 'goleveldb',
        },
        base_port: 26820,
        'coin-type': 60,
        coins: '100000000000000000000atest',
        config: {
          db_backend: 'goleveldb',
        },
        gas_prices: '0.01atest',
        mnemonic: '${VALIDATOR3_MNEMONIC}',
        staked: '10000000000000000000atest',
      },
    ],
  },
  relayer: {
    chains: [
      {
        address_type: {
          derivation: 'ethermint',
          proto_type: {
            pk_type: '/cosmos.evm.crypto.v1.ethsecp256k1.PubKey',
          },
        },
        event_source: {
          batch_delay: '5000ms',
        },
        extension_options: [
          {
            type: 'cosmos_evm_dynamic_fee_v1',
            value: '10000000000000000',
          },
        ],
        gas_multiplier: 1.1000000000000001,
        gas_price: {
          denom: 'uom',
          price: 0.10000000000000001,
        },
        id: 'mantra-canary-net-1',
        max_gas: 2500000,
      },
      {
        address_type: {
          derivation: 'ethermint',
          proto_type: {
            pk_type: '/cosmos.evm.crypto.v1.ethsecp256k1.PubKey',
          },
        },
        event_source: {
          batch_delay: '5000ms',
        },
        extension_options: [
          {
            type: 'cosmos_evm_dynamic_fee_v1',
            value: '10000000000000000',
          },
        ],
        gas_multiplier: 1.1,
        gas_price: {
          denom: 'atest',
          price: 0.1,
        },
        id: 'evm-canary-net-1',
        max_gas: 2500000,
      },
    ],
    mode: {
      channels: {
        enabled: true,
      },
      clients: {
        enabled: true,
        misbehaviour: true,
        refresh: true,
      },
      connections: {
        enabled: true,
      },
      packets: {
        enabled: true,
        tx_confirmation: true,
      },
    },
    rest: {
      enabled: true,
      host: '127.0.0.1',
      port: 3000,
    },
  },
}

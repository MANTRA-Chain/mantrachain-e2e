{
  dotenv: '../../scripts/.env',
  'mantra-canary-net-1': {
    cmd: 'mantrachaind',
    'start-flags': '--trace',
    config: {
      mempool: {
        version: 'v1',
      },
    },
    'app-config': {
      chain_id: 'mantra-canary-net-1',
      evm: {
        'evm-chain-id': 5887,
      },
      grpc: {
        'skip-check-header': true,
      },
      'minimum-gas-prices': '0uom',
      'index-events': ['ethereum_tx.ethereumTxHash'],
      'iavl-lazy-loading': true,
      'json-rpc': {
        enable: true,
        address: '127.0.0.1:{EVMRPC_PORT}',
        'ws-address': '127.0.0.1:{EVMRPC_PORT_WS}',
        api: 'eth,net,web3,debug',
        'feehistory-cap': 100,
        'block-range-cap': 10000,
        'logs-cap': 10000,
        'gas-cap': 30000000,
      },
    },
    validators: [{
      'coin-type': 60,
      coins: '100001000000uom',
      staked: '1000000uom',
      mnemonic: '${VALIDATOR1_MNEMONIC}',
    }, {
      'coin-type': 60,
      coins: '100001000000uom',
      staked: '1000000uom',
      mnemonic: '${VALIDATOR2_MNEMONIC}',
      config: {
        db_backend: 'pebbledb',
      },
      'app-config': {
        'app-db-backend': 'pebbledb',
      },
    }, {
      'coin-type': 60,
      coins: '100001000000uom',
      staked: '1000000uom',
      mnemonic: '${VALIDATOR3_MNEMONIC}',
      config: {
        db_backend: 'goleveldb',
      },
      'app-config': {
        'app-db-backend': 'goleveldb',
      },
    }],
    accounts: [{
      'coin-type': 60,
      name: 'community',
      coins: '100000000000uom',
      mnemonic: '${COMMUNITY_MNEMONIC}',
    }, {
      'coin-type': 60,
      name: 'signer1',
      coins: '20000000000000000000000uom',
      mnemonic: '${SIGNER1_MNEMONIC}',
    }, {
      'coin-type': 60,
      name: 'signer2',
      coins: '30000000000000000000000uom',
      mnemonic: '${SIGNER2_MNEMONIC}',
    }, {
      'coin-type': 60,
      name: 'reserve',
      coins: '100000000000uom',
      vesting: '60s',
    }],
    genesis: {
      consensus: {
        params: {
          block: {
            max_bytes: '3000000',
            max_gas: '300000000',
          },
          abci: {
            vote_extensions_enable_height: '1',
          },
        },
      },
      app_state: {
        evm: {
          params: {
            evm_denom: 'uom',
          },
        },
        feemarket: {
          params: {
            base_fee: '0.010000000000000000',
            min_gas_price: '0.000000000000000000',
            min_gas_multiplier: '0',
          },
        },
        gov: {
          params: {
            expedited_voting_period: '1s',
            voting_period: '10s',
            max_deposit_period: '10s',
            min_deposit: [
              {
                denom: 'uom',
                amount: '1',
              },
            ],
            expedited_min_deposit: [
              {
                denom: 'uom',
                amount: '2',
              },
            ],
          },
        },
        staking: {
          params: {
            bond_denom: 'uom',
          },
        },
      },
    },
  },
}

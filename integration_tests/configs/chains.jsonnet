{
  evmd: {
    'account-prefix': 'cosmos',
    evm_denom: 'atest',
    cmd: 'evmd',
    chain_id: 'evmd_262144-1',
    evm_chain_id: 262144,
    bank: {
      denom_metadata: [{
        description: 'Native 18-decimal denom metadata for Cosmos EVM chain',
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
        base: 'atest',
        display: 'test',
        name: 'Cosmos EVM',
        symbol: 'ATOM',
      }],
    },
    evm: {},
    feemarket: {
      params: {
        base_fee: '1000000000',
        min_gas_price: '0',
      },
    },
  },
  mantrachaind: {
    'account-prefix': 'mantra',
    evm_denom: 'amantra',
    cmd: 'mantrachaind',
    chain_id: 'mantra-canary-net-1',
    evm_chain_id: 7888,
    bank: {
      denom_metadata: [{
        description: 'The native staking token of the Mantrachain.',
        denom_units: [
          {
            denom: 'amantra',
            exponent: 0,
          },
          {
            denom: 'mantra',
            exponent: 18,
          },
        ],
        base: 'amantra',
        display: 'mantra',
        name: 'mantra',
        symbol: 'MANTRA',
      }],
    },
    evm: {
      params: {
        active_static_precompiles: [
          '0x0000000000000000000000000000000000000a01',
        ],
        extended_denom_options: {
          extended_denom: 'amantra',
        },
      },
    },
    feemarket: {
      params: {
        base_fee: '40000000000',
        min_gas_price: '40000000000',
      },
    },
  },
  nvnmchaind: {
    'account-prefix': 'nvnm',
    evm_denom: 'ibc/63C02A419B6F71F81AB7350335AB55D8A491D6926DFA91D1C8E226E1CABD419E',
    cmd: 'nvnmchaind',
    chain_id: 'nvnm_58886-1',
    evm_chain_id: 58886,
    bank: {
      denom_metadata: [{
        description: 'The wrapped version of MantraUSD, which is the ERC20 token bridged from the provider chain and used as the gas token on the consumer chain.',
        denom_units: [
          {
            denom: 'ibc/63C02A419B6F71F81AB7350335AB55D8A491D6926DFA91D1C8E226E1CABD419E',
            exponent: 0,
          },
          {
            denom: 'wmantrausd',
            exponent: 18,
          },
        ],
        base: 'ibc/63C02A419B6F71F81AB7350335AB55D8A491D6926DFA91D1C8E226E1CABD419E',
        display: 'wmantrausd',
        name: 'transfer/channel-1/wmantraUSD IBC token',
        symbol: 'wmantraUSD',
      }],
    },
    evm: {
      params: {
        active_static_precompiles: [
          '0x0000000000000000000000000000000000000A00',
        ],
      },
    },
    anchoring: {
      params: {
        admin: 'nvnm1nk2e2mhmz6qe8s44htqyxvdm48cey82dyntvry',  // reserve
      },
    },
    feemarket: {
      params: {
        base_fee: '87600000000',
        min_gas_price: '87600000000',
      },
    },
  },
  simd: {
    'account-prefix': 'cosmos',
    'coin-type': 118,
    evm_denom: 'stake',
    cmd: 'simd',
    chain_id: 'simd-test-1',
    evm_chain_id: 7888,
    bank: {},
    evm: {},
    feemarket: {},
  },
}

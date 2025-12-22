{
  evmd: {
    'account-prefix': 'cosmos',
    evm_denom: 'atest',
    cmd: 'evmd',
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
    evm_denom: 'uom',
    cmd: 'mantrachaind',
    evm_chain_id: 7888,
    bank: {
      denom_metadata: [{
        description: 'The native staking token of the Mantrachain.',
        denom_units: [
          {
            denom: 'uom',
          },
          {
            denom: 'om',
            exponent: 6,
          },
        ],
        base: 'uom',
        display: 'om',
        name: 'om',
        symbol: 'OM',
      }],
    },
    evm: {
      params: {
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
  inveniamd: {
    'account-prefix': 'inveniam',
    evm_denom: 'anvnm',
    cmd: 'inveniamd',
    evm_chain_id: 58886,
    bank: {
      denom_metadata: [{
        description: 'Native 18-decimal denom metadata for Cosmos EVM chain',
        denom_units: [
          {
            denom: 'anvnm',
            exponent: 0,
          },
          {
            denom: 'nvnm',
            exponent: 18,
          },
        ],
        base: 'anvnm',
        display: 'nvnm',
        name: 'nvnm',
        symbol: 'NVNM',
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
        admin: 'inveniam1x7x9pkfxf33l87ftspk5aetwnkr0lvlvyde8p7',
      },
    },
    feemarket: {
      params: {
        base_fee: '1000000000',
        min_gas_price: '0',
      },
    },
  },
  simd: {
    'account-prefix': 'cosmos',
    'coin-type': 118,
    evm_denom: 'stake',
    cmd: 'simd',
    evm_chain_id: 7888,
    bank: {},
    evm: {},
    feemarket: {},
  },
}

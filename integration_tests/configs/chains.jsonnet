{
  evmd: {
    'account-prefix': 'cosmos',
    evm_denom: 'atest',
    cmd: 'evmd',
    evm_chain_id: 262144,
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
    evm: {
      params: {
        allow_unprotected_txs: true,
      },
    },
    feemarket: {
      params: {
        base_fee: '0.010000000000000000',
        min_gas_price: '0.010000000000000000',
      },
    },
  },
  inveniemd: {
    'account-prefix': 'inveniem',
    evm_denom: 'anvnm',
    cmd: 'inveniemd',
    evm_chain_id: 7888,
    evm: {
      params: {
        allow_unprotected_txs: true,
      },
    },
    feemarket: {
      params: {
        base_fee: '1000000000',
        min_gas_price: '0',
      },
    },
  },
}

{
  evmd: {
    evm_denom: 'atest',
    cmd: 'evmd',
    chain_id: 9001,
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
    evm_denom: 'uom',
    cmd: 'mantrachaind',
    chain_id: 'mantra-canary-net-1',
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
}

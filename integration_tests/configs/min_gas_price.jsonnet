local config = import 'default.jsonnet';

config {
  'mantra-canary-net-1'+: {
    validators: [validator {
      gas_prices: '0.1uom',
    } for validator in super.validators],
    genesis+: {
      app_state+: {
        feemarket+: {
          params+: {
            base_fee_change_denominator: '3',
            elasticity_multiplier: '4',
            base_fee: '100',
            min_gas_price: '100',
          },
        },
      },
    },
  },
}

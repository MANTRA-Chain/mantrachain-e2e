local config = import 'default.jsonnet';
local basic = config['mantra-canary-net-1'];
local common = {
  'account-prefix': 'mantra',
  'coin-type': 60,
  'app-config'+: {
    'index-events': super['index-events'] + ['message.action'],
  },
  genesis+: {
    app_state+: {
      feemarket+: {
        params+: {
          no_base_fee: true,
          base_fee: '0',
        },
      },
    },
  },
};
local rly = {
  max_gas: 2500000,
  gas_multiplier: 1.1,
  address_type: {
    derivation: 'ethermint',
    proto_type: {
      pk_type: '/cosmos.evm.crypto.v1.ethsecp256k1.PubKey',
    },
  },
  gas_price: {
    price: 0.1,
    denom: 'uom',
  },
  event_source: {
    batch_delay: '5000ms',
  },
  extension_options: [{
    type: 'cosmos_evm_dynamic_fee',
    value: '10000000000000000',
  }],
};

config {
  'mantra-canary-net-1'+: common {
    key_name: 'signer1',
  },
  'mantra-canary-net-2'+: basic + common {
    key_name: 'signer2',
    validators: [validator {
      base_port: 26800 + i * 10,
    } for i in std.range(0, std.length(super.validators) - 1) for validator in [super.validators[i]]],
  },
  relayer: {
    mode: {
      clients: {
        enabled: true,
        refresh: true,
        misbehaviour: true,
      },
      connections: {
        enabled: true,
      },
      channels: {
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
    chains: [
      rly {
        id: 'mantra-canary-net-1',
      },
      rly {
        id: 'mantra-canary-net-2',
      },
    ],
  },
}

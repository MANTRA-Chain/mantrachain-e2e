local config = import 'default.jsonnet';

config {
  'mantra-canary-net-1'+: {
    genesis+: {
      app_state+: {
        erc20+: {
          token_pairs+: [
            {
              contract_owner: 1,
              erc20_address: '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE',
              denom: 'aom',
              enabled: true,
            },
          ],
          params+: {
            native_precompiles: ['0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE'],
          },
          native_precompiles:: super.native_precompiles,
        },
      },
    },
  },
}

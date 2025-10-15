local config = import 'hw.jsonnet';

config {
  'mantra-canary-net-1'+: {
    hw_account+: {
      'coin-type':: super['coin-type'],
    },
  },
}

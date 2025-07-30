local config = import 'default.jsonnet';

config {
  'mantra-canary-net-1'+: {
    accounts: super.accounts[:std.length(super.accounts) - 1] + [
      {
        'coin-type': 60,
        name: 'user' + i,
        coins: '100000000000uom',
      }
      for i in std.range(0, 5)
    ],
  },
}

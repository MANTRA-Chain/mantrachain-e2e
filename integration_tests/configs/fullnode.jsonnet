local config = import 'default.jsonnet';

config {
  'mantra-canary-net-1'+: {
    validators: super.validators[0:1] + [{
      name: 'fullnode',
    }],
  },
}

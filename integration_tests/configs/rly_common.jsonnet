{
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
      // default 100 blocks is slower than the test wait timeouts
      clear_interval: 10,
    },
  },
  rest: {
    enabled: true,
    host: '127.0.0.1',
    port: 3000,
  },
}

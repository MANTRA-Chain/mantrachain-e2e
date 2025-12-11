std.manifestYamlDoc({
  services: {
    ['testplan-' + i]: {
      image: 'mantra-testground:dnwx11r7d2wz16wk08b85wcmp7n93pli',
      command: 'stateless-testcase run',
      container_name: 'testplan-' + i,
      volumes: [
        std.extVar('outputs') + ':/outputs',
      ],
      environment: {
        JOB_COMPLETION_INDEX: i,
      },
    }
    for i in std.range(0, std.extVar('nodes') - 1)
  },
})

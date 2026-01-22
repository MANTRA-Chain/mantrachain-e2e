std.manifestYamlDoc({
  services: {
    ['testplan-' + i]: {
      image: std.extVar('image_name') + ':' + std.extVar('image_tag'),
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

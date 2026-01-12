{
  dockerTools,
  runCommandLocal,
  mantrachaind,
  benchmark-testcase,
}:
let
  tmpDir = runCommandLocal "tmp" { } ''
    mkdir -p $out/tmp/
  '';
in
dockerTools.buildLayeredImage {
  name = "mantra-testground";
  created = "now";
  contents = [
    benchmark-testcase
    mantrachaind
    tmpDir
  ];
  config = {
    Expose = [
      9090
      26657
      26656
      1317
      26658
      26660
      26659
      30000
    ];
    Cmd = [ "/bin/stateless-testcase" ];
    Env = [ "PYTHONUNBUFFERED=1" ];
  };
}

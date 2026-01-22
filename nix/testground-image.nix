{
  dockerTools,
  runCommandLocal,
  chaind,
  benchmark-testcase,
  imageName,
}:
let
  tmpDir = runCommandLocal "tmp" { } ''
    mkdir -p $out/tmp/
  '';
in
dockerTools.buildLayeredImage {
  name = imageName;
  created = "now";
  contents = [
    benchmark-testcase
    chaind
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

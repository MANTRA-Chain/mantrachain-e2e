{
  system ? builtins.currentSystem,
  pkgs ? import ../nix { inherit system; },
  includeMantrachaind ? true,
}:
pkgs.mkShell {
  buildInputs = [
    pkgs.git
    pkgs.test-env
    pkgs.poetry
    pkgs.go-ethereum
    pkgs.cosmovisor
    pkgs.start-scripts
    pkgs.hermes
    pkgs.cargo
    pkgs.rustc
    pkgs.rustfmt
    pkgs.solc
  ] ++ pkgs.lib.optionals includeMantrachaind [
    pkgs.mantrachaind
  ];
  shellHook = ''
    export TMPDIR=/tmp
    # Add wasm32-unknown-unknown target
    rustup target add wasm32-unknown-unknown 2>/dev/null || true
  '';
}

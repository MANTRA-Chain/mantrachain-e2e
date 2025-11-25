1. python -m benchmark.stateless generic-gen "$(cat benchmark/config.json)"
2. python -m benchmark.stateless run --datadir /tmp/data/out --global-seq 0 --outdir /outputs --binary mantrachaind

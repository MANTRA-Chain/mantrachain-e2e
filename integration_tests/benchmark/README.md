# Benchmark

## Prerequisites

- nix with flakes enabled
- Docker (via colima on macOS)
- linux-builder running (`nix run nixpkgs#darwin.linux-builder`)

## Steps

### 1. Build testground image for Linux

```bash
nix build .#packages.aarch64-linux.testground-image \
  --store 'ssh-ng://builder@linux-builder?ssh-key=/etc/nix/builder_ed25519' \
  --eval-store auto

scp -i /etc/nix/builder_ed25519 "builder@linux-builder:$(nix path-info --store 'ssh-ng://builder@linux-builder?ssh-key=/etc/nix/builder_ed25519' .#packages.aarch64-linux.testground-image)" ./mantra-testground.tar.gz

export DOCKER_HOST="unix://$HOME/.colima/default/docker.sock"
export IMAGE_TAG=$(docker load < mantra-testground.tar.gz | sed -n 's/.*mantra-testground://p')
echo "Image tag: $IMAGE_TAG"
```

### 2. Generate test data

```bash
rm -rf /tmp/data && nix build .#benchmark-testcase -o benchmark-testcase
./benchmark-testcase/bin/stateless-testcase generic-gen '{
  "outdir": "/tmp/data/out",
  "validators": 1,
  "fullnodes": 0,
  "validator_generate_load": true,
  "num_accounts": 800,
  "num_txs": 20,
  "tx_type": "simple-transfer",
  "app_patch": {
    "json-rpc": {"enable": true},
    "mempool": {"max-txs": -1}
  },
  "config_patch": {
    "mempool": {"size": 50000},
    "consensus": {"timeout_commit": "20ms"}
  },
  "genesis_patch": {
    "consensus": {"params": {"block": {"max_gas": "363000000"}}},
    "app_state": {
      "bank": {
        "denom_metadata": [{
          "base": "amantra",
          "denom_units": [
            {"denom": "amantra", "exponent": 0},
            {"denom": "mantra", "exponent": 18}
          ],
          "description": "The native staking token of the Mantrachain.",
          "display": "mantra",
          "name": "mantra",
          "symbol": "MANTRA"
        }]
      },
      "evm": {"params": {"extended_denom_options": {"extended_denom": "amantra"}}}
    }
  }
}'
```

### 3. Patch image with test data

```bash
./benchmark-testcase/bin/stateless-testcase patchimage \
  mantra-testground:$IMAGE_TAG \
  /tmp/data/out \
  --fromimage mantra-testground:$IMAGE_TAG
```

### 4. Run benchmark

```bash
jsonnet -S integration_tests/compositions/docker-compose.jsonnet \
  --ext-str image_tag=$IMAGE_TAG \
  --ext-str outputs=/tmp/colima \
  --ext-code nodes=1 \
| docker-compose -f /dev/stdin up --remove-orphans --force-recreate
```

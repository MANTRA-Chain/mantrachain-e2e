# Benchmark

## Prerequisites

- nix with flakes enabled
- Docker (via colima on macOS)
- linux-builder running (`nix run nixpkgs#darwin.linux-builder`)

## Steps

### 1. Set chain config

```bash
# config chain (mantrachaind, evmd)
export CHAIN_CONFIG=evmd

export DOCKER_HOST="unix://$HOME/.colima/default/docker.sock"
```

### 2. Build testground image for Linux

```bash
scripts/build-testground-image.sh $CHAIN_CONFIG
source scripts/artifacts/testground-image.env
```

### 3. Generate test data

```bash
rm -rf /tmp/data && nix build .#benchmark-testcase -o benchmark-testcase
./benchmark-testcase/bin/stateless-testcase generic-gen \
  "$(jsonnet integration_tests/benchmark/testcase-config.jsonnet --ext-str CHAIN_CONFIG=$CHAIN_CONFIG)"
```

### 4. Patch image with test data

```bash
./benchmark-testcase/bin/stateless-testcase patchimage \
  $IMAGE_NAME:$IMAGE_TAG \
  /tmp/data/out \
  --fromimage $IMAGE_NAME:$IMAGE_TAG
```

### 5. Run benchmark

```bash
jsonnet -S integration_tests/compositions/docker-compose.jsonnet \
  --ext-str image_name=$IMAGE_NAME \
  --ext-str image_tag=$IMAGE_TAG \
  --ext-str outputs=/tmp/colima \
  --ext-code nodes=1 \
| docker-compose -f /dev/stdin up --remove-orphans --force-recreate
```

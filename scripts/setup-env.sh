#!/bin/bash
# Setup environment variables for integration tests
# This script can be sourced to set up the environment without running tests

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export TMPDIR=/tmp

load_env_file() {
  local env_file="$1"
  if [ -f "$env_file" ]; then
    echo "Loading environment variables from $(basename "$env_file")"
    set -a
    source "$env_file"
    set +a
  else
    echo "ERROR: $(basename "$env_file") not found. Please create it from $(basename "$env_file").template." >&2
    return 1
  fi
}

load_env_file "$SCRIPT_DIR/.env" || return 1

CHAIN_CONFIG="${CHAIN_CONFIG:-mantrachaind}"

# Override chain-specific environment variables based on CHAIN_CONFIG
case "$CHAIN_CONFIG" in
  evmd)
    export EVM_CHAIN_ID=262144
    export EVM_DENOM="atest"
    export EVM_EXTENDED_DENOM="atest"
    export DEFAULT_GAS_AMT=10000000000
    export CMD="evmd"
    export WEI_PER_DENOM=1
    export ADDRESS_PREFIX="cosmos"
    ;;
  mantrachaind|"")
    export EVM_CHAIN_ID=7888
    export EVM_DENOM="amantra"
    export EVM_EXTENDED_DENOM="amantra"
    export DEFAULT_GAS_AMT=40000000000
    export CMD="mantrachaind"
    export WEI_PER_DENOM=1
    export ADDRESS_PREFIX="mantra"
    ;;
  inveniamd)
    export EVM_CHAIN_ID=58886
    export EVM_DENOM="anvnm"
    export EVM_EXTENDED_DENOM="anvnm"
    export DEFAULT_GAS_AMT=10000000000
    export CMD="inveniamd"
    export WEI_PER_DENOM=1
    export ADDRESS_PREFIX="inveniam"
    ;;
  *)
    echo "Unknown CHAIN_CONFIG: $CHAIN_CONFIG"
    return 1
    ;;
esac

echo "Chain config: $CHAIN_CONFIG (CMD=$CMD, EVM_DENOM=$EVM_DENOM)"

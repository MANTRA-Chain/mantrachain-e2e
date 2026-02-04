#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR/../integration_tests"

source "$SCRIPT_DIR/setup-env.sh"

TESTS_TO_RUN="${TESTS_TO_RUN:-all}"

# pytest command with chain-config
build_pytest_cmd() {
  local base_cmd="$1"
  if [[ -n "$CHAIN_CONFIG" ]]; then
    echo "$base_cmd --chain-config $CHAIN_CONFIG"
  else
    echo "$base_cmd"
  fi
}

if [[ "${NIX_LITE_MODE}" == "true" ]]; then
  echo "Lite mode detected"
else
  echo "Full mode"
fi

if [[ "$TESTS_TO_RUN" == "all" ]]; then
  echo "run all local tests (excluding ccv)"
  cmd=$(build_pytest_cmd "uv run pytest -s -vvv -m \"not connect\" --ignore=test_ccv.py")
elif [[ "$TESTS_TO_RUN" == "connect" ]]; then
  echo "run tests matching $TESTS_TO_RUN"
  cmd=$(build_pytest_cmd "uv run pytest -vv -s -m connect")
elif [[ "$TESTS_TO_RUN" == "evmd" ]]; then
  echo "run evmd-specific tests"
  cmd=$(build_pytest_cmd "uv run pytest -vvv -s -m evmd")
else
  echo "run tests matching $TESTS_TO_RUN"
  cmd=$(build_pytest_cmd "uv run pytest -vv -s -m \"$TESTS_TO_RUN\"")
fi

eval $cmd
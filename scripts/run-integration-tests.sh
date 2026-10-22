#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# explicitly set a short TMPDIR to prevent path too long issue on macosx
export TMPDIR=/tmp

cd "$SCRIPT_DIR/../integration_tests"

env_file="$SCRIPT_DIR/.env"
if [ ! -f "$env_file" ]; then
  echo "ERROR: .env not found. Please create it from env.template." >&2
  exit 1
fi
echo "Loading environment variables from .env"
set -a
source "$env_file"
set +a

TESTS_TO_RUN="${TESTS_TO_RUN:-all}"

if [[ "${NIX_LITE_MODE}" == "true" ]]; then
  echo "Lite mode detected"
else
  echo "Full mode"
fi

if [[ "$TESTS_TO_RUN" == "all" ]]; then
  echo "run all local tests (excluding ccv)"
  args=(-s -vvv -m "not connect" --ignore=test_ccv.py)
else
  echo "run tests matching $TESTS_TO_RUN"
  args=(-vv -s -m "$TESTS_TO_RUN")
fi
if [[ -n "$CHAIN_CONFIG" ]]; then
  args+=(--chain-config "$CHAIN_CONFIG")
fi

uv run pytest "${args[@]}"

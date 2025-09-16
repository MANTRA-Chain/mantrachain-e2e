#!/bin/bash
set -e

# explicitly set a short TMPDIR to prevent path too long issue on macosx
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export TMPDIR=/tmp

cd "$SCRIPT_DIR/../integration_tests"

TESTS_TO_RUN="${TESTS_TO_RUN:-all}"

load_env_file() {
  local env_file="$1"
  if [ -f "$env_file" ]; then
    echo "Loading environment variables from $(basename "$env_file")"
    set -a
    source "$env_file"
    set +a
  else
    echo "ERROR: $(basename "$env_file") not found. Please create it from $(basename "$env_file").template." >&2
    exit 1
  fi
}

if [[ "$TESTS_TO_RUN" == "all" ]]; then
  load_env_file "$SCRIPT_DIR/.env"
  echo "run all local tests"
  pytest -s -vvv -m "not connect"
elif [[ "$TESTS_TO_RUN" == "connect" ]]; then
  load_env_file "$SCRIPT_DIR/.env"
  load_env_file "$SCRIPT_DIR/network.env"
  echo "run tests matching $TESTS_TO_RUN"
  pytest -vv -s -m connect
else
  load_env_file "$SCRIPT_DIR/.env"
  echo "run tests matching $TESTS_TO_RUN"
  pytest -vv -s -m "$TESTS_TO_RUN"
fi
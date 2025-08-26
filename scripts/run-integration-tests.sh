#!/bin/bash
set -e
cd "$(dirname "$0")"

# explicitly set a short TMPDIR to prevent path too long issue on macosx
export TMPDIR=/tmp

git submodule update --init --recursive
cd ../integration_tests

TESTS_TO_RUN="${TESTS_TO_RUN:-all}"

if [[ "$TESTS_TO_RUN" == "all" ]]; then
  echo "run all local tests"
  pytest -s -vvv -m "not connect"
elif [[ "$TESTS_TO_RUN" == "connect" ]]; then
  if [ -f ../scripts/network.env ]; then
    echo "Loading environment variables from network.env"
    set -a
    source ../scripts/network.env
    set +a
  else
    echo "ERROR: network.env not found. Please create it from scripts/network.env.template." >&2
    exit 1
  fi
  echo "run tests matching $TESTS_TO_RUN"
  pytest -vv -s -m connect
else
  echo "run tests matching $TESTS_TO_RUN"
  pytest -vv -s -m $TESTS_TO_RUN
fi

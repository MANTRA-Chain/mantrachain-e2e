#!/bin/bash
set -e
cd "$(dirname "$0")"

# explicitly set a short TMPDIR to prevent path too long issue on macosx
export TMPDIR=/tmp

echo "build test contracts"
cd ../integration_tests/contracts
HUSKY_SKIP_INSTALL=1 npm install
npm run typechain
cd ..

TESTS_TO_RUN="${TESTS_TO_RUN:-all}"

if [[ "$TESTS_TO_RUN" == "all" ]]; then
  echo "run all tests"
  pytest -v -s -m unmarked
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
  pytest -v -s -m $TESTS_TO_RUN
fi

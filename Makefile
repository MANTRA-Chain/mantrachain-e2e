#!/usr/bin/make -f

CHAIN_CONFIG ?= mantrachaind
TESTS_TO_RUN ?= all

test-e2e-nix:
	@echo "CHAIN_CONFIG=$(CHAIN_CONFIG) TESTS_TO_RUN=$(TESTS_TO_RUN)"
	@bash scripts/restore_envs.sh
	@CHAIN_CONFIG=$(CHAIN_CONFIG) TESTS_TO_RUN=$(TESTS_TO_RUN) nix develop --accept-flake-config -c bash scripts/run-integration-tests.sh

test-e2e-nix-skip-mantrachaind-build:
	@echo "CHAIN_CONFIG=$(CHAIN_CONFIG) TESTS_TO_RUN=$(TESTS_TO_RUN) (lite mode - using local mantrachaind)"
	@echo "Local mantrachaind: $$(which mantrachaind || echo 'NOT FOUND - Please ensure mantrachaind is in PATH')"
	@bash scripts/restore_envs.sh
	@CHAIN_CONFIG=$(CHAIN_CONFIG) TESTS_TO_RUN=$(TESTS_TO_RUN) NIX_LITE_MODE=true nix develop --accept-flake-config --impure .#lite -c bash scripts/run-integration-tests.sh

test-connect-e2e-nix:
	@echo "CHAIN_CONFIG=$(CHAIN_CONFIG) TESTS_TO_RUN=connect"
	@bash scripts/restore_envs.sh
	@CHAIN_CONFIG=$(CHAIN_CONFIG) TESTS_TO_RUN=connect nix develop --accept-flake-config -c bash scripts/run-integration-tests.sh

dev:
	nix develop --accept-flake-config -c bash

dev-lite:
	NIX_LITE_MODE=true nix develop --accept-flake-config --impure .#lite -c bash

lint-py:
	@cd integration_tests && uv run flake8 --show-source --count --statistics --format="::error file=%(path)s,line=%(row)d,col=%(col)d::%(path)s:%(row)d:%(col)d: %(code)s %(text)s"

.PHONY: test-e2e-nix test-e2e-nix-skip-mantrachaind-build test-connect-e2e-nix dev dev-lite lint-py

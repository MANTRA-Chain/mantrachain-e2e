#!/usr/bin/make -f

CHAIN_CONFIG ?= mantrachaind
TESTS_TO_RUN ?= all

NIX_DEV_CMD = nix develop --accept-flake-config -c
NIX_DEV_CMD_LITE = nix develop --accept-flake-config --impure -c

ifdef IN_NIX_SHELL
  ENTER_NIX =
  ENTER_NIX_LITE =
else
  ENTER_NIX = $(NIX_DEV_CMD)
  ENTER_NIX_LITE = INCLUDE_MANTRACHAIND=0 $(NIX_DEV_CMD_LITE)
endif

test-e2e-nix:
	@echo "CHAIN_CONFIG=$(CHAIN_CONFIG) TESTS_TO_RUN=$(TESTS_TO_RUN)"
	@bash scripts/restore_envs.sh
	@CHAIN_CONFIG=$(CHAIN_CONFIG) TESTS_TO_RUN=$(TESTS_TO_RUN) $(ENTER_NIX) bash scripts/run-integration-tests.sh

test-e2e-nix-skip-mantrachaind-build:
	@echo "CHAIN_CONFIG=$(CHAIN_CONFIG) TESTS_TO_RUN=$(TESTS_TO_RUN) (lite mode)"
	@bash scripts/restore_envs.sh
	@CHAIN_CONFIG=$(CHAIN_CONFIG) TESTS_TO_RUN=$(TESTS_TO_RUN) $(ENTER_NIX_LITE) bash scripts/run-integration-tests.sh

test-connect-e2e-nix:
	@echo "CHAIN_CONFIG=$(CHAIN_CONFIG) TESTS_TO_RUN=connect"
	@bash scripts/restore_envs.sh
	@CHAIN_CONFIG=$(CHAIN_CONFIG) TESTS_TO_RUN=connect $(ENTER_NIX) bash scripts/run-integration-tests.sh

dev:
	@$(NIX_DEV_CMD) bash

dev-lite:
	@$(ENTER_NIX_LITE) bash

lint-py:
	@cd integration_tests && uv run flake8 --show-source --count --statistics --format="::error file=%(path)s,line=%(row)d,col=%(col)d::%(path)s:%(row)d:%(col)d: %(code)s %(text)s"

.PHONY: test-e2e-nix test-e2e-nix-skip-mantrachaind-build test-connect-e2e-nix dev dev-lite lint-py

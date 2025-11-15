#!/usr/bin/make -f

CHAIN_CONFIG ?=
TESTS_TO_RUN ?=

test-e2e-nix:
	@bash ./scripts/restore_envs.sh
	@nix develop --command bash -c "cd integration_tests && uv sync && CHAIN_CONFIG=$(CHAIN_CONFIG) TESTS_TO_RUN=all ../scripts/run-integration-tests.sh"

test-e2e-nix-skip-mantrachaind-build:
	@bash ./scripts/restore_envs.sh
	@INCLUDE_MANTRACHAIND=0 nix develop --command bash -c "cd integration_tests && uv sync && CHAIN_CONFIG=$(CHAIN_CONFIG) TESTS_TO_RUN=all ../scripts/run-integration-tests.sh"

test-connect-e2e-nix:
	@bash ./scripts/restore_envs.sh
	@nix develop --command bash -c "cd integration_tests && uv sync && TESTS_TO_RUN=connect CHAIN_CONFIG=$(CHAIN_CONFIG) ../scripts/run-integration-tests.sh"

lint-py:
	@cd integration_tests && uv sync && uv run flake8 --show-source --count --statistics --format="::error file=%(path)s,line=%(row)d,col=%(col)d::%(path)s:%(row)d:%(col)d: %(code)s %(text)s"

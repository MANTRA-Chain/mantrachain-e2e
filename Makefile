#!/usr/bin/make -f

NIX_DEV_CMD = nix develop --accept-flake-config -c

ifdef IN_NIX_SHELL
  ENTER_NIX =
else
  ENTER_NIX = $(NIX_DEV_CMD)
endif

test-e2e-nix:
	@echo "TESTS_TO_RUN=$(TESTS_TO_RUN)"
	@bash scripts/restore_envs.sh
	@$(ENTER_NIX) bash scripts/run-integration-tests.sh

test-connect-e2e-nix:
	@bash scripts/restore_envs.sh
	@TESTS_TO_RUN=connect $(ENTER_NIX) bash scripts/run-integration-tests.sh

dev:
	@$(NIX_DEV_CMD) bash

lint-py:
	@cd integration_tests && uv sync && uv run flake8 --show-source --count --statistics --format="::error file=%(path)s,line=%(row)d,col=%(col)d::%(path)s:%(row)d:%(col)d: %(code)s %(text)s"

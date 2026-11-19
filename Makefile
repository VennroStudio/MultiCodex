.DEFAULT_GOAL := help

PROJECT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
export ACCOUNT FROM TO
RUN = /bin/bash "$(PROJECT_DIR)/scripts/multicodex.sh"

.PHONY: help status launch setup sync preview

help:
	@$(RUN) help

status:
	@$(RUN) status

launch setup:
	@$(RUN) $@ --account "$$ACCOUNT"

sync preview:
	@$(RUN) $@ --from-account "$$FROM" --to-account "$$TO"

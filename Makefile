# Thin façade over scripts/code-quality.sh and install.py.
# CI calls the script directly; these targets exist for humans.

.DEFAULT_GOAL := help

.PHONY: help check lint shell typecheck test format validate sync \
	install install-claude install-copilot uninstall telemetry clean-telemetry

help:  ## List available targets
	@grep -E '^[a-z][a-z-]*:.*##' $(MAKEFILE_LIST) | \
		awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

check:  ## Full quality gate (same command CI runs)
	bash scripts/code-quality.sh all

lint:  ## ruff format --check + ruff check
	bash scripts/code-quality.sh lint

shell:  ## bashate over the maintained shell scripts
	bash scripts/code-quality.sh shell

typecheck:  ## ty
	bash scripts/code-quality.sh typecheck

test:  ## compileall + pytest
	bash scripts/code-quality.sh test

format:  ## Mutating: ruff format + ruff check --fix (local only)
	bash scripts/code-quality.sh format

validate:  ## Installer parity + criteria drift validation
	bash scripts/code-quality.sh validate

sync:  ## Regenerate worker agents from shared/agents/
	uv run python install.py sync

install:  ## Install both targets (Claude Code + Copilot)
	uv run python install.py install --target all

install-claude:  ## Install the Claude Code target
	uv run python install.py install --target claude

install-copilot:  ## Install the GitHub Copilot target
	uv run python install.py install --target copilot

uninstall:  ## Uninstall both targets
	uv run python install.py uninstall --target all

telemetry:  ## Summarize a session's telemetry.md (pass SESSION=.agentmaster/sessions/<id>/telemetry.md)
	uv run python scripts/telemetry_report.py $(SESSION)

clean-telemetry:  ## Prune a session's telemetry, snapshots, and stale starts (pass SESSION=.agentmaster/sessions/<id>)
	uv run python scripts/telemetry_report.py --prune $(if $(SESSION),$(SESSION)/telemetry.md,)

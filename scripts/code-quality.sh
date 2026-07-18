#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/log.sh
source "$SCRIPT_DIR/log.sh"

run_lint() {
    local failed=0

    log_step "ruff format --check"
    if ! uv run ruff format . --check; then
        log_error "Format check failed — run 'bash scripts/code-quality.sh format' locally to fix"
        failed=1
    fi
    log_step_end

    log_step "ruff check"
    if ! uv run ruff check .; then
        log_error "Lint check failed"
        failed=1
    fi
    log_step_end

    return $failed
}

run_format() {
    log_step "ruff format"
    uv run ruff format .
    log_step_end

    log_step "ruff check --fix"
    uv run ruff check . --fix --unsafe-fixes
    log_step_end

    log_success "Formatting complete"
}

run_typecheck() {
    local failed=0

    log_step "ty check"
    if ! uv run ty check; then
        log_error "Type check failed"
        failed=1
    fi
    log_step_end

    return $failed
}

run_pycompile() {
    local failed=0

    log_step "py-compile"
    if ! uv run python -m compileall -q app/ test/; then
        log_error "Compile check failed"
        failed=1
    fi
    log_step_end

    return $failed
}

run_all() {
    local failed=0

    run_lint || failed=1
    run_typecheck || failed=1
    run_pycompile || failed=1

    if [[ $failed -eq 1 ]]; then
        log_error "One or more quality checks failed"
        exit 1
    fi

    log_success "All quality checks passed"
}

case "${1:-all}" in
    lint)   run_lint || exit 1;;
    format) run_format;;
    typecheck)  run_typecheck;;
    py-compile) run_pycompile;;
    all) run_all;;
    *)
        echo "Usage: $(basename "$0") [lint|format|typecheck|py-compile|all]" >&2
        exit 1
        ;;
esac
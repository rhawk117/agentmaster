#!/usr/bin/env bash
# Quality gate for agentmaster. Every command except `format` is check-only
# and never modifies files; CI runs `all`. Run from the repository root.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"
# shellcheck source=scripts/log.sh
source "$SCRIPT_DIR/log.sh"

# Maintained shell scripts checked by bashate. Ignored rules are stylistic:
# E006 (long lines) and E003 (indent width — log.sh uses consistent 2-space).
SHELL_SCRIPTS=(scripts/*.sh)
BASHATE_IGNORES="E003,E006"

run_lint() {
    local failed=0

    log_step "ruff format --check"
    if ! uv run ruff format . --check; then
        log_error "Format check failed — run 'bash scripts/code-quality.sh format' locally to fix"
        failed=1
    fi
    log_step_end

    log_step "ruff check (no fixes)"
    if ! uv run ruff check . --no-fix; then
        log_error "Lint check failed"
        failed=1
    fi
    log_step_end

    return $failed
}

run_shell() {
    local failed=0

    log_step "bashate"
    if ! uv run bashate -i "$BASHATE_IGNORES" "${SHELL_SCRIPTS[@]}"; then
        log_error "Shell lint failed"
        failed=1
    fi
    log_step_end

    return $failed
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

run_test() {
    local failed=0
    local -a targets=()
    local path

    for path in install.py installer hooks scripts tests; do
        [[ -e "$path" ]] && targets+=("$path")
    done

    log_step "py-compile"
    if [[ ${#targets[@]} -gt 0 ]] && ! uv run python -m compileall -q "${targets[@]}"; then
        log_error "Compile check failed"
        failed=1
    fi
    log_step_end

    log_step "pytest (unit: not subprocess and not integration)"
    if ! uv run python -m pytest -m "not subprocess and not integration" tests/; then
        log_error "Unit tests failed"
        failed=1
    fi
    log_step_end

    log_step "pytest (subprocess: subprocess and not integration)"
    if ! uv run python -m pytest -m "subprocess and not integration" tests/; then
        log_error "Subprocess tests failed"
        failed=1
    fi
    log_step_end

    log_step "pytest (integration)"
    if ! uv run python -m pytest -m integration tests/; then
        log_error "Integration tests failed"
        failed=1
    fi
    log_step_end

    return $failed
}

run_validate() {
    local failed=0

    log_step "installer parity validation"
    if ! uv run python install.py validate; then
        log_error "Parity validation failed"
        failed=1
    fi
    log_step_end

    return $failed
}

# Mutating: local use only — never wired into `all` or CI.
run_format() {
    log_step "ruff format"
    uv run ruff format .
    log_step_end

    log_step "ruff check --fix"
    uv run ruff check . --fix --unsafe-fixes
    log_step_end

    log_success "Formatting complete"
}

run_all() {
    local failed=0

    run_lint || failed=1
    run_shell || failed=1
    run_typecheck || failed=1
    run_test || failed=1
    run_validate || failed=1

    if [[ $failed -eq 1 ]]; then
        log_error "One or more quality checks failed"
        exit 1
    fi

    log_success "All quality checks passed"
}

case "${1:-all}" in
    lint)      run_lint || exit 1;;
    shell)     run_shell || exit 1;;
    typecheck) run_typecheck || exit 1;;
    test)      run_test || exit 1;;
    validate)  run_validate || exit 1;;
    format)    run_format;;
    all)       run_all;;
    *)
        echo "Usage: $(basename "$0") [lint|shell|typecheck|test|validate|format|all]" >&2
        exit 1
        ;;
esac

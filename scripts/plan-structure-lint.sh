#!/usr/bin/env bash
# Structural lint for agentmaster-plan output (Phase 5 post-formalize gate).
# Checks a plan file for the required elements: execution contract, toolchain
# section, execution-mode declaration, implementer (sonnet) executor tags,
# Uses: lines, per-task verification, shared resources, open questions, and
# the closing review gate — plus the E12(b)/E18 citation rule: task text
# must cite ledger entry numbers, never a raw evidence/*.md path. Exits
# non-zero listing every missing or violating element; exits 0 when the
# plan conforms.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/log.sh
source "$SCRIPT_DIR/log.sh"

usage() {
    echo "Usage: $(basename "$0") <plan-file>" >&2
    exit 2
}

[[ $# -eq 1 ]] || usage
PLAN_FILE="$1"
[[ -f "$PLAN_FILE" ]] || { log_error "No such file: $PLAN_FILE"; exit 2; }

declare -a FAILURES=()

check_pattern() {
    local label="$1"
    local pattern="$2"
    if ! grep -Eqi "$pattern" "$PLAN_FILE"; then
        FAILURES+=("$label")
    fi
}

# Tolerant patterns: case-insensitive headings, colon optional on
# "Execution mode", and Verify:/Verification: as documented variants.
check_pattern "execution contract line (\"Executed only by agentmaster-execute ...\")" \
    'Executed only by agentmaster-execute dispatching implementer workers'
check_pattern "## Toolchain section" '^#+[[:space:]]*Toolchain'
check_pattern "Execution mode declaration" '^#+[[:space:]]*Execution mode:?'
check_pattern 'implementer (sonnet) executor tag' 'implementer \(sonnet\)'
check_pattern 'Uses: line' 'Uses:'
check_pattern 'per-task verification (Verify:|Verification:)' '(Verify|Verification):'
check_pattern 'Shared resources section' '^#+[[:space:]]*Shared resources'
check_pattern 'Open Questions section' '^#+[[:space:]]*Open Questions'
check_pattern 'review gate (agentmaster-review)' 'review gate|agentmaster-review'

# Citation rule (E12(b)/E18): task text must cite ledger entry numbers, not
# a raw evidence/*.md path. Exempt the Evidence ledger section, which
# legitimately names evidence files in prose — reset on every heading line.
BODY="$(awk '
    {
        line = $0
        if (line ~ /^#+[[:space:]]/) {
            in_ledger = (tolower(line) ~ /evidence[[:space:]]+ledger/) ? 1 : 0
        }
        if (!in_ledger) print line
    }
' "$PLAN_FILE")"

if grep -Eq 'evidence/[A-Za-z0-9_./-]+\.md' <<< "$BODY"; then
    FAILURES+=('task text cites a raw evidence/*.md path — cite the ledger entry number instead')
fi

if [[ ${#FAILURES[@]} -gt 0 ]]; then
    log_error "Plan structure lint failed for $PLAN_FILE:"
    for item in "${FAILURES[@]}"; do
        printf '  - %s\n' "$item" >&2
    done
    exit 1
fi

log_success "Plan structure lint passed for $PLAN_FILE"

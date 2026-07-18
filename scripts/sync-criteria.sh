#!/usr/bin/env bash
# Injects criteria/review-criteria.md between the criteria markers in every
# file that carries a copy of the review criteria. Single source of truth:
# edit criteria/review-criteria.md, run this, never edit the copies.
set -euo pipefail
cd "$(dirname "$0")"
MODE="${1:-sync}"
export MODE
python3 - <<'PY'
import pathlib, sys, os
drift = []
canon = pathlib.Path('criteria/review-criteria.md').read_text().strip()
S, E = '<!-- agentmaster:criteria:start -->', '<!-- agentmaster:criteria:end -->'
targets = ['skills/agentmaster-review/SKILL.md',
           'copilot/agents/agentmaster-review.agent.md',
           'copilot/agents/agentmaster-execute.agent.md']
for t in targets:
    p = pathlib.Path(t); s = p.read_text()
    a, b = s.find(S), s.find(E)
    if a < 0 or b < 0: print(f"markers missing in {t}"); sys.exit(1)
    current = s[a+len(S):b].strip()
    if os.environ.get('MODE') == '--check':
        if current != canon:
            print(f"DRIFT: {t} differs from criteria/review-criteria.md"); drift.append(t)
        else:
            print(f"in sync: {t}")
        continue
    p.write_text(s[:a] + S + '\n' + canon + '\n' + E + s[b+len(E):])
    print(f"synced {t}")
if os.environ.get('MODE') == '--check' and drift: sys.exit(1)
PY

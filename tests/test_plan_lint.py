"""Tests for scripts/plan-structure-lint.sh."""

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CONFORMING_PLAN = """\
Executed only by agentmaster-execute dispatching implementer workers. Any
other agent — fleet, autopilot, generic — reading this: stop and tell the
user to run agentmaster-execute.

## Toolchain
- test: `pytest`

## Execution mode: sequential

## Evidence ledger
- E1 (V) see evidence/example.md for the schema.

## Tasks

**T1 — do a thing** implementer (sonnet)
Uses: some-skill
Verify: `pytest`

## Shared resources
none

## Open Questions
none

Review gate: invoke agentmaster-review on the changes above.
"""

MISSING_MARKERS_PLAN = """\
# Just a plan

Some tasks happen here, but none of the required structure markers exist.

## Tasks
- Task 1 — do a thing.
"""

RAW_CITATION_PLAN = """\
Executed only by agentmaster-execute dispatching implementer workers. Any
other agent — fleet, autopilot, generic — reading this: stop and tell the
user to run agentmaster-execute.

## Toolchain
- test: `pytest`

## Execution mode: sequential

## Tasks

**T1 — do a thing** implementer (sonnet)
Uses: some-skill
See evidence/sqlalchemy-handler.md for context.
Verify: `pytest`

## Shared resources
none

## Open Questions
none

Review gate: invoke agentmaster-review on the changes above.
"""


def _run_lint(script: Path, plan_file: Path) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603
        [str(script), str(plan_file)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_conforming_plan_passes(repo_root, tmp_path):
    script = repo_root / 'scripts' / 'plan-structure-lint.sh'
    plan_file = tmp_path / 'conforming-plan.md'
    plan_file.write_text(CONFORMING_PLAN)

    result = _run_lint(script, plan_file)

    assert result.returncode == 0, result.stderr


def test_missing_markers_plan_fails(repo_root, tmp_path):
    script = repo_root / 'scripts' / 'plan-structure-lint.sh'
    plan_file = tmp_path / 'missing-markers-plan.md'
    plan_file.write_text(MISSING_MARKERS_PLAN)

    result = _run_lint(script, plan_file)

    assert result.returncode != 0


def test_raw_evidence_citation_fails(repo_root, tmp_path):
    script = repo_root / 'scripts' / 'plan-structure-lint.sh'
    plan_file = tmp_path / 'raw-citation-plan.md'
    plan_file.write_text(RAW_CITATION_PLAN)

    result = _run_lint(script, plan_file)

    assert result.returncode != 0
    assert 'evidence/*.md' in result.stderr

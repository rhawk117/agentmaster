from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.orchestrator_state import RunTransitionInput, transition_run

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable, Sequence

PREFLIGHT_CATEGORIES: tuple[str, ...] = (
    'repository',
    'worktree',
    'base_sha',
    'configuration',
    'tools',
    'dependencies',
    'ledger_health',
    'delivery_authority',
    'budgets',
)


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    name: str
    passed: bool
    detail: str = ''


@dataclass(frozen=True, slots=True)
class PreflightResult:
    passed: bool
    checks: tuple[PreflightCheck, ...]
    blocked_reason: str | None


def run_preflight(
    connection: sqlite3.Connection,
    run_id: str,
    checks: Sequence[PreflightCheck],
    *,
    now: str,
    id_factory: Callable[[], str],
) -> PreflightResult:
    seen = {check.name for check in checks}
    missing = [name for name in PREFLIGHT_CATEGORIES if name not in seen]
    if missing:
        raise ValueError(f'run_preflight: missing checks for {missing}')

    failed = [check for check in checks if not check.passed]
    if failed:
        reason = '; '.join(f'{check.name}: {check.detail}' for check in failed)
        transition_run(
            connection,
            run_id,
            'Blocked',
            RunTransitionInput(now=now, id_factory=id_factory, reason=reason),
        )
        return PreflightResult(passed=False, checks=tuple(checks), blocked_reason=reason)

    transition_run(
        connection,
        run_id,
        'Executing',
        RunTransitionInput(now=now, id_factory=id_factory),
    )
    return PreflightResult(passed=True, checks=tuple(checks), blocked_reason=None)

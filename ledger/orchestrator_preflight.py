"""Orchestrator preflight, gating RUN Preflight->Executing/Blocked (SPEC.md §9, §23 M19).

SPEC.md §23 Microtask 19: "Add preflight for repository, worktree, base SHA,
configuration, tools, dependencies, ledger health, delivery authority, and
budgets." Each category's actual check (a git call, a config load, a tool
probe, a budget lookup) lives with whichever caller has that information;
this module only enforces that every category was checked and turns the
result into a legality-checked RUN transition, so a caller cannot silently
drop a category and pass by omission (SPEC.md §9: "must not ... hide budget
exhaustion").
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.orchestrator_state import RunTransitionInput, transition_run

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable, Sequence

# SPEC.md §23 Microtask 19's exact preflight category list.
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
    """One preflight category's pass/fail result and, on failure, why."""

    name: str
    passed: bool
    detail: str = ''


@dataclass(frozen=True, slots=True)
class PreflightResult:
    """The outcome of one `run_preflight` call."""

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
    """Validate `checks` cover every preflight category, then transition `run_id`.

    Every check passing transitions the RUN to `'Executing'`. Any failing
    check transitions it to `'Blocked'` with a reason naming each failing
    category and its detail (SPEC.md §9.1: "Preflight --> Blocked: missing
    authority or dependency").

    Raises
    ------
    ValueError
        `checks` does not cover exactly `PREFLIGHT_CATEGORIES` (a caller
        bug: a preflight run must check every category, not skip one).
    RunNotFoundError
        No RUN row exists for `run_id`.
    IllegalTransitionError
        `run_id` is not currently in the `'Preflight'` state.
    """
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

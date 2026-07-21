"""Evidence sufficiency for task acceptance criteria (SPEC.md §9.4, §23 Microtask 20).

SPEC.md §9.4: "A task is verifiable only when each acceptance criterion has
at least one evidence record or an explicit reason that manual verification
is required." `TASK.acceptance_json` holds a JSON array of criteria (each an
object with at least `id`, optionally `manual_verification_reason`);
`EVIDENCE.criterion_id` is the free-text join key a caller uses to attach an
evidence row to one criterion (`ledger.evidence.record_command_evidence`).
This module only reads those two; it records nothing itself.
"""

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3


class TaskNotFoundError(ValueError):
    """No TASK row exists for the requested id."""


@dataclass(frozen=True, slots=True)
class AcceptanceCriterion:
    """One parsed criterion from `TASK.acceptance_json`."""

    criterion_id: str
    text: str
    manual_verification_reason: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceGap:
    """One acceptance criterion with neither evidence nor a manual-verification reason."""

    criterion_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class EvidenceSufficiencyResult:
    """The outcome of one `check_evidence_sufficiency` call."""

    sufficient: bool
    gaps: tuple[EvidenceGap, ...]


def parse_acceptance_criteria(
    acceptance_json: str | None,
) -> tuple[AcceptanceCriterion, ...]:
    """Parse `TASK.acceptance_json` into its acceptance criteria.

    Returns an empty tuple for `None` or an empty JSON array — a task with no
    recorded criteria has nothing to be insufficient about.
    """
    if not acceptance_json:
        return ()
    return tuple(
        AcceptanceCriterion(
            criterion_id=item['id'],
            text=item.get('text', ''),
            manual_verification_reason=item.get('manual_verification_reason'),
        )
        for item in json.loads(acceptance_json)
    )


def _evidenced_criterion_ids(connection: sqlite3.Connection, task_id: str) -> set[str]:
    rows = connection.execute(
        'SELECT DISTINCT criterion_id FROM EVIDENCE '
        'WHERE task_id = ? AND criterion_id IS NOT NULL',
        (task_id,),
    ).fetchall()
    return {row[0] for row in rows}


def check_evidence_sufficiency(
    connection: sqlite3.Connection, task_id: str
) -> EvidenceSufficiencyResult:
    """Check that every acceptance criterion on `task_id` is evidenced or excused.

    Raises
    ------
    TaskNotFoundError
        No TASK row exists for `task_id`.
    """
    row = connection.execute(
        'SELECT acceptance_json FROM TASK WHERE id = ?', (task_id,)
    ).fetchone()
    if row is None:
        raise TaskNotFoundError(task_id)

    criteria = parse_acceptance_criteria(row[0])
    evidenced = _evidenced_criterion_ids(connection, task_id)
    gaps = tuple(
        EvidenceGap(
            criterion_id=criterion.criterion_id,
            reason='no evidence record and no manual-verification reason',
        )
        for criterion in criteria
        if criterion.criterion_id not in evidenced
        and criterion.manual_verification_reason is None
    )
    return EvidenceSufficiencyResult(sufficient=not gaps, gaps=gaps)

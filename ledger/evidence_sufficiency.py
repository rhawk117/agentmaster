import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3


class TaskNotFoundError(ValueError): ...


@dataclass(frozen=True, slots=True)
class AcceptanceCriterion:
    criterion_id: str
    text: str
    manual_verification_reason: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceGap:
    criterion_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class EvidenceSufficiencyResult:
    sufficient: bool
    gaps: tuple[EvidenceGap, ...]


def parse_acceptance_criteria(
    acceptance_json: str | None,
) -> tuple[AcceptanceCriterion, ...]:
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

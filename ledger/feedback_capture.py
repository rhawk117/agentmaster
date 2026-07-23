import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ledger.feedback import FeedbackInput, record_feedback
from ledger.orchestrator_state import RUN_COMPLETION_HOOKS
from ledger.retrospective import MemoryCandidateProposal, propose_memory_candidate
from ledger.transactions import run_write_transaction

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

_HARMFUL_RATING = -1
_NEUTRAL_RATING = 0
_HELPFUL_RATING = 1


@dataclass(frozen=True, slots=True)
class FeedbackPrompt:
    rating: int
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class _CaptureContext:
    run_id: str
    project_id: str
    feedback_id: str
    id_factory: Callable[[], str]
    now: str


def _isatty_prompt() -> FeedbackPrompt | None:
    if not sys.stdin.isatty():
        return None
    try:
        raw = input(
            'Rate this run (-1 unhelpful, 0 neutral, 1 helpful, Enter to skip): '
        ).strip()
    except EOFError, OSError:
        return None
    if raw not in ('-1', '0', '1'):
        return None
    comment = input('Optional comment (Enter to skip): ').strip() or None
    return FeedbackPrompt(rating=int(raw), comment=comment)


def _apply_feedback_to_used_memories(
    connection: sqlite3.Connection, run_id: str, rating: int
) -> None:
    if rating == _NEUTRAL_RATING:
        return
    memory_ids = [
        row[0]
        for row in connection.execute(
            'SELECT DISTINCT memory_id FROM memory_access WHERE run_id = ?', (run_id,)
        ).fetchall()
    ]
    if not memory_ids:
        return
    helpful = 1 if rating == _HELPFUL_RATING else 0
    harmful = 1 if rating == _HARMFUL_RATING else 0
    counter_column = 'usefulness_count' if rating == _HELPFUL_RATING else 'harmful_count'

    def _update(conn: sqlite3.Connection) -> None:
        conn.executemany(
            'UPDATE memory_access SET helpful = ?, harmful = ? '
            'WHERE run_id = ? AND memory_id = ?',
            [(helpful, harmful, run_id, memory_id) for memory_id in memory_ids],
        )
        conn.executemany(
            f'UPDATE MEMORY SET {counter_column} = {counter_column} + 1 '  # noqa: S608
            'WHERE id = ?',
            [(memory_id,) for memory_id in memory_ids],
        )

    run_write_transaction(connection, _update)


def _propose_candidate_from_feedback(
    connection: sqlite3.Connection, context: _CaptureContext, answer: FeedbackPrompt
) -> None:
    if answer.rating == _NEUTRAL_RATING:
        return
    evidence_row = connection.execute(
        'SELECT id FROM EVIDENCE WHERE run_id = ? ORDER BY id LIMIT 1', (context.run_id,)
    ).fetchone()
    observation_row = connection.execute(
        'SELECT ro.id FROM RETRO_OBSERVATION ro '
        'JOIN RETROSPECTIVE r ON r.id = ro.retrospective_id '
        "WHERE r.run_id = ? AND ro.observation_kind = 'outcome' "
        'ORDER BY ro.id LIMIT 1',
        (context.run_id,),
    ).fetchone()
    if evidence_row is None or observation_row is None:
        return

    sentiment = 'helpful' if answer.rating == _HELPFUL_RATING else 'unhelpful'
    memory_id = context.id_factory()
    propose_memory_candidate(
        connection,
        MemoryCandidateProposal(
            memory_id=memory_id,
            project_id=context.project_id,
            memory_kind='user-feedback',
            title=f'User feedback ({sentiment}) on run {context.run_id}',
            content=answer.comment or f'User rated run {context.run_id} as {sentiment}.',
            observation_id=observation_row[0],
            evidence_id=evidence_row[0],
        ),
        created_at=context.now,
    )

    def _link(conn: sqlite3.Connection) -> None:
        conn.execute(
            'UPDATE FEEDBACK SET memory_id = ? WHERE id = ?',
            (memory_id, context.feedback_id),
        )

    run_write_transaction(connection, _link)


def capture_feedback(
    connection: sqlite3.Connection,
    run_id: str,
    *,
    prompt: Callable[[], FeedbackPrompt | None],
    id_factory: Callable[[], str],
    now: str,
) -> str | None:
    answer = prompt()
    if answer is None:
        return None

    run_row = connection.execute(
        'SELECT user_session_id, project_id FROM RUN WHERE id = ?', (run_id,)
    ).fetchone()
    if run_row is None:
        return None
    user_session_id, project_id = run_row

    feedback_id = id_factory()
    record_feedback(
        connection,
        FeedbackInput(
            id=feedback_id,
            user_session_id=user_session_id,
            run_id=run_id,
            rating=answer.rating,
            created_at=now,
            comment=answer.comment,
        ),
    )
    _apply_feedback_to_used_memories(connection, run_id, answer.rating)
    _propose_candidate_from_feedback(
        connection,
        _CaptureContext(
            run_id=run_id,
            project_id=project_id,
            feedback_id=feedback_id,
            id_factory=id_factory,
            now=now,
        ),
        answer,
    )
    return feedback_id


def capture_feedback_on_completion(connection: sqlite3.Connection, run_id: str) -> None:
    capture_feedback(
        connection,
        run_id,
        prompt=_isatty_prompt,
        id_factory=lambda: str(uuid.uuid4()),
        now=datetime.now(UTC).isoformat(),
    )


def register_feedback_capture_hook() -> None:
    if capture_feedback_on_completion not in RUN_COMPLETION_HOOKS:
        RUN_COMPLETION_HOOKS.append(capture_feedback_on_completion)

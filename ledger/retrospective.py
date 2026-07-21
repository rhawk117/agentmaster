"""Post-delivery retrospective loop: read-only observations to write-typed
retrospective records and candidate memories (SPEC.md §9.1, §18, §20.4, §23
Microtask 23).

The improvement loop's first two steps are "record structured execution and
evidence" (already done by the time a RUN reaches `RetrospectivePending`) and
"complete an outcome-aware retrospective" (§20.4). `gather_observations` reads
only the stable, allow-listed views SPEC.md §18 names -- never a raw table --
over a `ledger.connection.connect_read_only` connection, so the retrospective
capability never needs write authority to observe. `run_retrospective` then
writes the RETROSPECTIVE/RETRO_OBSERVATION rows those observations become and,
"after the configured delivery terminal state and before run completion"
(§23 M23), advances the RUN from `RetrospectivePending` to `Complete` --
which is what fires the `RUN_COMPLETION_HOOKS` a later microtask attaches its
feedback-capture callback to (SPEC.md §9.1: "the run's retrospective must
exist before feedback is solicited").

`propose_memory_candidate` is the loop's third step, "propose candidate
memories" (§20.4): it creates a Candidate MEMORY row scoped only to the
retrospective's originating project, never global (§18: "Retrospectives
create candidates, never active/global knowledge directly") and links it to
the observation and evidence it came from. Validation, activation, and
cross-project promotion are `ledger.memory_service`/`ledger.improvement_policy`
concerns, not this module's.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.orchestrator_state import RunTransitionInput, transition_run
from ledger.transactions import run_write_transaction

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable


class RunNotReadyForRetrospectiveError(ValueError):
    """RUN `run_id` has not reached `RetrospectivePending`, so no retrospective
    may start yet.
    """


@dataclass(frozen=True, slots=True)
class RetrospectiveClock:
    """The clock and id minting one `run_retrospective` call needs."""

    now: str
    id_factory: Callable[[], str]


@dataclass(frozen=True, slots=True)
class ObservationDraft:
    """One RETRO_OBSERVATION row `run_retrospective` is about to write."""

    observation_kind: str
    claim: str
    confidence: str | None = None
    counterfactual: str | None = None


@dataclass(frozen=True, slots=True)
class RetrospectiveResult:
    """The outcome of one `run_retrospective` call."""

    retrospective_id: str
    observation_ids: tuple[str, ...]
    outcome: str | None
    summary: str | None


def _outcome_observations(
    read_connection: sqlite3.Connection, run_id: str
) -> list[ObservationDraft]:
    row = read_connection.execute(
        'SELECT state, task_count, completed_task_count FROM v_run_summary '
        'WHERE run_id = ?',
        (run_id,),
    ).fetchone()
    if row is None:
        return []
    state, task_count, completed_task_count = row
    return [
        ObservationDraft(
            observation_kind='outcome',
            claim=(
                f'run ended {state} with {completed_task_count}/{task_count} '
                'task(s) complete'
            ),
            confidence='descriptive',
        )
    ]


def _efficiency_observations(
    read_connection: sqlite3.Connection, run_id: str
) -> list[ObservationDraft]:
    rows = read_connection.execute(
        'SELECT role, call_count, input_tokens, output_tokens '
        'FROM v_token_usage_by_role WHERE run_id = ? ORDER BY role',
        (run_id,),
    ).fetchall()
    return [
        ObservationDraft(
            observation_kind='efficiency',
            claim=(
                f'{role}: {call_count} model call(s), {input_tokens or 0} input + '
                f'{output_tokens or 0} output token(s)'
            ),
            confidence='descriptive',
        )
        for role, call_count, input_tokens, output_tokens in rows
    ]


def _quality_observations(
    read_connection: sqlite3.Connection, run_id: str
) -> list[ObservationDraft]:
    attempt_ids = [
        row[0]
        for row in read_connection.execute(
            'SELECT DISTINCT delivery_attempt_id FROM v_delivery_current_head '
            'WHERE run_id = ?',
            (run_id,),
        ).fetchall()
    ]
    if not attempt_ids:
        return []
    placeholders = ','.join('?' * len(attempt_ids))
    # `placeholders` is a fixed run of `?` marks sized from `attempt_ids`, not
    # interpolated user input; every value is still bound below.
    query = (
        'SELECT severity, summary FROM v_unresolved_review_findings '  # noqa: S608
        f'WHERE delivery_attempt_id IN ({placeholders})'
    )
    rows = read_connection.execute(query, attempt_ids).fetchall()
    return [
        ObservationDraft(
            observation_kind='quality',
            claim=f'unresolved {severity} finding: {summary}',
            confidence='descriptive',
            counterfactual='would remain unresolved without a follow-up task',
        )
        for severity, summary in rows
    ]


_FEEDBACK_SENTIMENTS: dict[int, str] = {-1: 'unhelpful', 0: 'neutral', 1: 'helpful'}


def _feedback_observations(
    read_connection: sqlite3.Connection, run_id: str
) -> list[ObservationDraft]:
    rows = read_connection.execute(
        'SELECT rating, comment FROM v_run_feedback WHERE run_id = ? ORDER BY created_at',
        (run_id,),
    ).fetchall()
    return [
        ObservationDraft(
            observation_kind='feedback',
            claim=(
                f'user feedback: {_FEEDBACK_SENTIMENTS[rating]}'
                + (f' -- {comment}' if comment else '')
            ),
            confidence='descriptive',
        )
        for rating, comment in rows
    ]


def gather_observations(
    read_connection: sqlite3.Connection, run_id: str
) -> list[ObservationDraft]:
    """Build descriptive observations for `run_id` from allow-listed views only.

    Reads `v_run_summary` (outcome), `v_token_usage_by_role` (efficiency),
    `v_delivery_current_head`/`v_unresolved_review_findings` (quality), and
    `v_run_feedback` (feedback) -- never a raw table -- matching SPEC.md §18:
    "connects read-only to allow-listed views."
    """
    return [
        *_outcome_observations(read_connection, run_id),
        *_efficiency_observations(read_connection, run_id),
        *_quality_observations(read_connection, run_id),
        *_feedback_observations(read_connection, run_id),
    ]


def _existing_retrospective(
    write_connection: sqlite3.Connection, run_id: str
) -> tuple[str, str, str | None, str | None] | None:
    return write_connection.execute(
        'SELECT id, status, outcome, summary FROM RETROSPECTIVE WHERE run_id = ?',
        (run_id,),
    ).fetchone()


def _observation_ids(
    write_connection: sqlite3.Connection, retrospective_id: str
) -> tuple[str, ...]:
    rows = write_connection.execute(
        'SELECT id FROM RETRO_OBSERVATION WHERE retrospective_id = ? ORDER BY id',
        (retrospective_id,),
    ).fetchall()
    return tuple(row[0] for row in rows)


def run_retrospective(
    write_connection: sqlite3.Connection,
    read_connection: sqlite3.Connection,
    run_id: str,
    clock: RetrospectiveClock,
) -> RetrospectiveResult:
    """Complete `run_id`'s retrospective and advance it to `Complete`.

    Idempotent: a run whose retrospective is already `Complete` returns the
    existing result without recreating observations or re-transitioning the
    run, so interruption recovery can retry this call safely.

    Raises
    ------
    RunNotReadyForRetrospectiveError
        `run_id`'s RUN row is not currently `RetrospectivePending`.
    """
    existing = _existing_retrospective(write_connection, run_id)
    if existing is not None and existing[1] == 'Complete':
        return RetrospectiveResult(
            retrospective_id=existing[0],
            observation_ids=_observation_ids(write_connection, existing[0]),
            outcome=existing[2],
            summary=existing[3],
        )

    state_row = write_connection.execute(
        'SELECT state FROM RUN WHERE id = ?', (run_id,)
    ).fetchone()
    if state_row is None or state_row[0] != 'RetrospectivePending':
        raise RunNotReadyForRetrospectiveError(
            f'RUN {run_id} is not RetrospectivePending'
        )

    retrospective_id = existing[0] if existing is not None else clock.id_factory()
    drafts = gather_observations(read_connection, run_id)
    outcome = 'observed' if drafts else 'no_observations'
    summary = f'{len(drafts)} observation(s) recorded'

    def _write(conn: sqlite3.Connection) -> None:
        if existing is None:
            conn.execute(
                'INSERT INTO RETROSPECTIVE (id, run_id, status, created_at) '
                "VALUES (?, ?, 'Pending', ?)",
                (retrospective_id, run_id, clock.now),
            )
        for draft in drafts:
            conn.execute(
                'INSERT INTO RETRO_OBSERVATION '
                '(id, retrospective_id, observation_kind, claim, confidence, '
                'counterfactual, created_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (
                    clock.id_factory(),
                    retrospective_id,
                    draft.observation_kind,
                    draft.claim,
                    draft.confidence,
                    draft.counterfactual,
                    clock.now,
                ),
            )
        conn.execute(
            'UPDATE RETROSPECTIVE SET status = ?, outcome = ?, summary = ?, '
            'completed_at = ? WHERE id = ?',
            ('Complete', outcome, summary, clock.now, retrospective_id),
        )

    run_write_transaction(write_connection, _write)

    transition_run(
        write_connection,
        run_id,
        'Complete',
        RunTransitionInput(now=clock.now, id_factory=clock.id_factory),
    )

    return RetrospectiveResult(
        retrospective_id=retrospective_id,
        observation_ids=_observation_ids(write_connection, retrospective_id),
        outcome=outcome,
        summary=summary,
    )


@dataclass(frozen=True, slots=True)
class MemoryCandidateProposal:
    """Everything needed to create one Candidate MEMORY row from a retrospective."""

    memory_id: str
    project_id: str
    memory_kind: str
    title: str
    content: str
    observation_id: str
    evidence_id: str
    proposing_session_id: str | None = None
    confidence: str | None = None


def propose_memory_candidate(
    connection: sqlite3.Connection,
    proposal: MemoryCandidateProposal,
    *,
    created_at: str,
) -> str:
    """Create one Candidate MEMORY row, scoped to `proposal.project_id` only.

    Links the new memory to `proposal.observation_id`/`proposal.evidence_id`
    via a `'proposes'` MEMORY_EVIDENCE row (SPEC.md §18: "All conclusions link
    to evidence"). Never creates a global scope: SPEC.md §18: "Retrospectives
    create candidates, never active/global knowledge directly" -- global
    promotion is `ledger.improvement_policy`'s job, gated on independent,
    cross-project evidence.
    """

    def _insert(conn: sqlite3.Connection) -> None:
        conn.execute(
            'INSERT INTO MEMORY '
            '(id, origin_project_id, state, memory_kind, title, content, confidence, '
            'proposing_session_id, created_at, updated_at) '
            "VALUES (?, ?, 'Candidate', ?, ?, ?, ?, ?, ?, ?)",
            (
                proposal.memory_id,
                proposal.project_id,
                proposal.memory_kind,
                proposal.title,
                proposal.content,
                proposal.confidence,
                proposal.proposing_session_id,
                created_at,
                created_at,
            ),
        )
        conn.execute(
            'INSERT INTO MEMORY_SCOPE (memory_id, scope_kind, project_id, created_at) '
            "VALUES (?, 'project', ?, ?)",
            (proposal.memory_id, proposal.project_id, created_at),
        )
        conn.execute(
            'INSERT INTO MEMORY_EVIDENCE '
            '(memory_id, evidence_id, observation_id, relation, created_at) '
            "VALUES (?, ?, ?, 'proposes', ?)",
            (
                proposal.memory_id,
                proposal.evidence_id,
                proposal.observation_id,
                created_at,
            ),
        )

    run_write_transaction(connection, _insert)
    return proposal.memory_id

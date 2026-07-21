"""Memory search/show/lifecycle service behind `agentmaster memory` (SPEC.md §17.3-19).

Deferred from Microtask 14/15's schema-only work: this module adds the
retrieval and lifecycle-transition behavior those schemas support.

`MEMORY.proposing_session_id` records which session proposed a candidate, so
`validate_memory` enforces §17.4's session-independence rule ("evidence not
authored solely by the same session that proposed the candidate"): a
validating session id is mandatory, with no argument value that skips the
check. The schema does not yet record which
project(s) supplied validating evidence, so the deeper §17.4 policy check
("successful evidence from at least two distinct projects") remains left to
a future schema change; this module enforces the state-machine legality the
diagram in §17.4 defines and the evidence linkage §17.3 requires ("All
conclusions link to evidence").
"""

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.transactions import run_write_transaction

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

RETRIEVAL_ALGORITHM_VERSION = 'v1'
_TOKEN_ESTIMATE_CHARS_PER_TOKEN = 4

_LEGAL_TRANSITIONS: dict[str, tuple[str, ...]] = {
    'Candidate': ('Validated', 'Rejected'),
    'Validated': ('Active',),
    'Active': ('Superseded', 'Archived', 'Rejected'),
    'Superseded': ('Archived',),
    'Rejected': ('Archived',),
}


class MemoryNotFoundError(ValueError):
    """No MEMORY row exists for the requested id."""


class IllegalMemoryTransitionError(ValueError):
    """The requested state transition is not permitted by SPEC.md §17.4."""


def estimate_tokens(text: str) -> int:
    """Cheap, dependency-free token estimate (~4 characters per token)."""
    return max(1, len(text) // _TOKEN_ESTIMATE_CHARS_PER_TOKEN)


@dataclass(frozen=True, slots=True)
class MemorySearchScope:
    """Who is asking and where their search results get logged (SPEC.md §17.5)."""

    project_id: str
    run_id: str
    task_id: str | None = None
    agent_session_id: str | None = None


@dataclass(frozen=True, slots=True)
class MemorySearchResult:
    """One ranked memory candidate returned from `search_memories`."""

    memory_id: str
    title: str
    content: str
    memory_kind: str
    confidence: str | None
    rank: int
    score: float
    estimated_tokens: int


@dataclass(frozen=True, slots=True)
class MemoryAccessLog:
    """How to mint and timestamp the `memory_access` rows a search logs (§17.5)."""

    access_id_factory: Callable[[], str]
    created_at: str


def search_memories(
    connection: sqlite3.Connection,
    scope: MemorySearchScope,
    query: str,
    access_log: MemoryAccessLog,
    *,
    limit: int = 10,
) -> list[MemorySearchResult]:
    """Full-text search active/validated memories visible to `scope.project_id`.

    Matches project-scoped memories for `scope.project_id` plus global
    memories (SPEC.md §17.3: "Default retrieval includes the current project
    plus validated global memory"), then logs one `memory_access` row per
    returned candidate with its rank, score, and estimated token count
    (§17.5), using `access_log.access_id_factory()` to mint each row's id.
    """
    rows = connection.execute(
        'SELECT m.id, m.title, m.content, m.memory_kind, m.confidence, '
        'bm25(memory_fts) AS bm25_score '
        'FROM memory_fts '
        'JOIN MEMORY m ON m.rowid = memory_fts.rowid '
        'JOIN MEMORY_SCOPE ms ON ms.memory_id = m.id '
        'WHERE memory_fts MATCH ? '
        "AND (ms.scope_kind = 'global' OR ms.project_id = ?) "
        'ORDER BY bm25_score '
        'LIMIT ?',
        (query, scope.project_id, limit),
    ).fetchall()

    query_digest = hashlib.sha256(query.encode()).hexdigest()
    results = [
        MemorySearchResult(
            memory_id=row[0],
            title=row[1],
            content=row[2],
            memory_kind=row[3],
            confidence=row[4],
            rank=rank,
            score=-row[5],  # bm25() is lower-is-better; negate so higher score wins
            estimated_tokens=estimate_tokens(row[2]),
        )
        for rank, row in enumerate(rows)
    ]

    def _log(conn: sqlite3.Connection) -> None:
        for result in results:
            conn.execute(
                'INSERT INTO memory_access '
                '(id, run_id, task_id, agent_session_id, memory_id, query_digest, '
                'rank, score, selected, estimated_tokens, retrieval_algorithm_version, '
                'created_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)',
                (
                    access_log.access_id_factory(),
                    scope.run_id,
                    scope.task_id,
                    scope.agent_session_id,
                    result.memory_id,
                    query_digest,
                    result.rank,
                    result.score,
                    result.estimated_tokens,
                    RETRIEVAL_ALGORITHM_VERSION,
                    access_log.created_at,
                ),
            )

    if results:
        run_write_transaction(connection, _log)
    return results


@dataclass(frozen=True, slots=True)
class MemoryDetail:
    """The full MEMORY row for `agentmaster memory show`."""

    memory_id: str
    state: str
    memory_kind: str
    title: str
    content: str
    confidence: str | None
    usefulness_count: int
    harmful_count: int
    origin_project_id: str
    created_at: str
    updated_at: str


def show_memory(connection: sqlite3.Connection, memory_id: str) -> MemoryDetail | None:
    """Return the MEMORY row for `memory_id`, or `None` if it does not exist."""
    row = connection.execute(
        'SELECT id, state, memory_kind, title, content, confidence, usefulness_count, '
        'harmful_count, origin_project_id, created_at, updated_at '
        'FROM MEMORY WHERE id = ?',
        (memory_id,),
    ).fetchone()
    if row is None:
        return None
    return MemoryDetail(*row)


def _current_state(connection: sqlite3.Connection, memory_id: str) -> str:
    row = connection.execute(
        'SELECT state FROM MEMORY WHERE id = ?', (memory_id,)
    ).fetchone()
    if row is None:
        raise MemoryNotFoundError(memory_id)
    return row[0]


def _transition(
    connection: sqlite3.Connection, memory_id: str, to_state: str, *, updated_at: str
) -> None:
    current = _current_state(connection, memory_id)
    if to_state not in _LEGAL_TRANSITIONS.get(current, ()):
        raise IllegalMemoryTransitionError(
            f'{memory_id}: {current} -> {to_state} is not permitted'
        )

    def _update(conn: sqlite3.Connection) -> None:
        conn.execute(
            'UPDATE MEMORY SET state = ?, updated_at = ? WHERE id = ?',
            (to_state, updated_at, memory_id),
        )

    run_write_transaction(connection, _update)


def validate_memory(
    connection: sqlite3.Connection,
    memory_id: str,
    evidence_id: str,
    *,
    updated_at: str,
    validating_session_id: str | None,
) -> None:
    """Transition a Candidate memory to Validated and link its supporting evidence.

    Refuses the transition if `validating_session_id` matches the memory's
    `proposing_session_id`: SPEC.md §17.4 requires "evidence not authored
    solely by the same session that proposed the candidate." A validating
    session id is mandatory: passing `None` is rejected with a structured
    error rather than skipping the check.

    Raises
    ------
    IllegalMemoryTransitionError
        `validating_session_id` is `None`, or matches the proposing session.
    """
    if validating_session_id is None:
        raise IllegalMemoryTransitionError(
            f'{memory_id}: a validating session id is required (SPEC.md §17.4)'
        )
    row = connection.execute(
        'SELECT proposing_session_id FROM MEMORY WHERE id = ?', (memory_id,)
    ).fetchone()
    if row is None:
        raise MemoryNotFoundError(memory_id)
    proposing_session_id = row[0]
    if proposing_session_id is not None and proposing_session_id == validating_session_id:
        raise IllegalMemoryTransitionError(
            f'{memory_id}: validating session {validating_session_id!r} must '
            'differ from the proposing session (SPEC.md §17.4)'
        )

    _transition(connection, memory_id, 'Validated', updated_at=updated_at)

    def _link(conn: sqlite3.Connection) -> None:
        conn.execute(
            'INSERT INTO MEMORY_EVIDENCE '
            '(memory_id, evidence_id, observation_id, relation, strength, created_at) '
            "VALUES (?, ?, NULL, 'validates', NULL, ?)",
            (memory_id, evidence_id, updated_at),
        )

    run_write_transaction(connection, _link)


def activate_memory(
    connection: sqlite3.Connection, memory_id: str, *, updated_at: str
) -> None:
    """Transition a Validated memory to Active (approved scope, SPEC.md §17.4)."""
    _transition(connection, memory_id, 'Active', updated_at=updated_at)


def reject_memory(
    connection: sqlite3.Connection, memory_id: str, *, updated_at: str
) -> None:
    """Transition a Candidate or Active memory to Rejected (SPEC.md §17.4)."""
    current = _current_state(connection, memory_id)
    if current not in ('Candidate', 'Active'):
        raise IllegalMemoryTransitionError(
            f'{memory_id}: {current} -> Rejected is not permitted'
        )
    _transition(connection, memory_id, 'Rejected', updated_at=updated_at)


@dataclass(frozen=True, slots=True)
class NewMemoryInput:
    """The new MEMORY row `supersede_memory` creates in place of the old one."""

    id: str
    origin_project_id: str
    memory_kind: str
    title: str
    content: str
    confidence: str | None = None


def supersede_memory(
    connection: sqlite3.Connection,
    old_memory_id: str,
    new_memory: NewMemoryInput,
    *,
    updated_at: str,
) -> str:
    """Archive-track `old_memory_id` as Superseded and create `new_memory` as Active.

    Copies the old memory's MEMORY_SCOPE rows onto the new memory and records
    a `supersedes` MEMORY_LINK, matching SPEC.md §17.4: "Supersession creates
    a new memory and link; it does not overwrite history."
    """
    _transition(connection, old_memory_id, 'Superseded', updated_at=updated_at)
    scopes = connection.execute(
        'SELECT scope_kind, project_id, include_descendants FROM MEMORY_SCOPE '
        'WHERE memory_id = ?',
        (old_memory_id,),
    ).fetchall()

    def _insert(conn: sqlite3.Connection) -> None:
        conn.execute(
            'INSERT INTO MEMORY '
            '(id, origin_project_id, state, memory_kind, title, content, confidence, '
            'supersedes_memory_id, created_at, updated_at) '
            "VALUES (?, ?, 'Active', ?, ?, ?, ?, ?, ?, ?)",
            (
                new_memory.id,
                new_memory.origin_project_id,
                new_memory.memory_kind,
                new_memory.title,
                new_memory.content,
                new_memory.confidence,
                old_memory_id,
                updated_at,
                updated_at,
            ),
        )
        for scope_kind, project_id, include_descendants in scopes:
            conn.execute(
                'INSERT INTO MEMORY_SCOPE '
                '(memory_id, scope_kind, project_id, include_descendants, created_at) '
                'VALUES (?, ?, ?, ?, ?)',
                (new_memory.id, scope_kind, project_id, include_descendants, updated_at),
            )
        conn.execute(
            'INSERT INTO MEMORY_LINK '
            '(source_memory_id, target_memory_id, link_kind, weight, created_at) '
            "VALUES (?, ?, 'supersedes', NULL, ?)",
            (new_memory.id, old_memory_id, updated_at),
        )

    run_write_transaction(connection, _insert)
    return new_memory.id

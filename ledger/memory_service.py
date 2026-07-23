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


class MemoryNotFoundError(ValueError): ...


class IllegalMemoryTransitionError(ValueError): ...


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // _TOKEN_ESTIMATE_CHARS_PER_TOKEN)


@dataclass(frozen=True, slots=True)
class MemorySearchScope:
    project_id: str
    run_id: str
    task_id: str | None = None
    agent_session_id: str | None = None


@dataclass(frozen=True, slots=True)
class MemorySearchResult:
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
            score=-row[5],
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
    _transition(connection, memory_id, 'Active', updated_at=updated_at)


def reject_memory(
    connection: sqlite3.Connection, memory_id: str, *, updated_at: str
) -> None:
    current = _current_state(connection, memory_id)
    if current not in ('Candidate', 'Active'):
        raise IllegalMemoryTransitionError(
            f'{memory_id}: {current} -> Rejected is not permitted'
        )
    _transition(connection, memory_id, 'Rejected', updated_at=updated_at)


@dataclass(frozen=True, slots=True)
class NewMemoryInput:
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

"""Bounded, session-scoped context-pack builder (SPEC.md §9.3, §19, §23 Microtask 16).

Builds the pack contents SPEC.md §9.3 names for a dispatched agent: task and
project identity, selected memories with rank, the project's active
procedure versions, required evidence kinds, and a token budget with stop
conditions. Memory retrieval and its digest are recorded via
`ledger.memory_service.search_memories`, which logs one `memory_access` row
per candidate.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ledger.memory_service import (
    MemoryAccessLog,
    MemorySearchResult,
    MemorySearchScope,
    search_memories,
)

if TYPE_CHECKING:
    import sqlite3

# SPEC.md §9.4: the fixed set of evidence kinds acceptable for a criterion.
REQUIRED_EVIDENCE_KINDS: tuple[str, ...] = (
    'test-result',
    'command-result',
    'diff-inspection',
    'generated-parity-check',
    'artifact-hash',
    'ci-check',
    'reviewer-finding',
)


class SessionScopeError(ValueError):
    """The requested run/task does not belong to the given user session/project."""


class RunNotFoundError(ValueError):
    """No RUN row exists for the requested id."""


class TaskNotFoundError(ValueError):
    """No TASK row exists for the requested id."""


@dataclass(frozen=True, slots=True)
class ContextPackRequest:
    """The bounded inputs needed to build one task's context pack."""

    project_id: str
    user_session_id: str
    run_id: str
    task_id: str
    budget_tokens: int
    query: str | None = None


@dataclass(frozen=True, slots=True)
class SelectedMemory:
    """One memory selected into a context pack, with its retrieval rank."""

    memory_id: str
    title: str
    rank: int
    score: float
    estimated_tokens: int


@dataclass(frozen=True, slots=True)
class ContextPack:
    """A bounded, project-filtered context pack (SPEC.md §9.3)."""

    task_id: str
    project_id: str
    run_id: str
    user_session_id: str
    objective: str
    acceptance_criteria: str | None
    selected_memories: tuple[SelectedMemory, ...]
    procedure_versions: tuple[str, ...]
    required_evidence_kinds: tuple[str, ...]
    budget_tokens: int
    estimated_tokens: int
    stop_conditions: tuple[str, ...]
    digest: str


def _run_user_session_id(connection: sqlite3.Connection, run_id: str) -> str:
    row = connection.execute(
        'SELECT user_session_id FROM RUN WHERE id = ?', (run_id,)
    ).fetchone()
    if row is None:
        raise RunNotFoundError(run_id)
    return row[0]


def _task_row(
    connection: sqlite3.Connection, task_id: str, run_id: str
) -> tuple[str, str | None]:
    row = connection.execute(
        'SELECT title, acceptance_json, run_id FROM TASK WHERE id = ?', (task_id,)
    ).fetchone()
    if row is None:
        raise TaskNotFoundError(task_id)
    title, acceptance_json, task_run_id = row
    if task_run_id != run_id:
        raise SessionScopeError(f'task {task_id!r} does not belong to run {run_id!r}')
    return title, acceptance_json


def _active_procedure_versions(
    connection: sqlite3.Connection, project_id: str
) -> tuple[str, ...]:
    rows = connection.execute(
        'SELECT pv.id FROM PROCEDURE_VERSION pv '
        'JOIN PROCEDURE p ON p.id = pv.procedure_id '
        "WHERE p.project_id = ? AND pv.status = 'active' "
        'ORDER BY p.name, pv.version_no',
        (project_id,),
    ).fetchall()
    return tuple(row[0] for row in rows)


def _select_within_budget(
    candidates: list[MemorySearchResult], budget_tokens: int
) -> tuple[list[MemorySearchResult], bool]:
    selected: list[MemorySearchResult] = []
    used_tokens = 0
    truncated = False
    for candidate in candidates:
        if used_tokens + candidate.estimated_tokens > budget_tokens:
            truncated = True
            continue
        selected.append(candidate)
        used_tokens += candidate.estimated_tokens
    return selected, truncated


def build_context_pack(
    connection: sqlite3.Connection, request: ContextPackRequest, *, created_at: str
) -> ContextPack:
    """Build a bounded context pack for `request`, scoped to its user session.

    Raises
    ------
    SessionScopeError
        `request.run_id` does not belong to `request.user_session_id`, or
        `request.task_id` does not belong to `request.run_id`.
    RunNotFoundError, TaskNotFoundError
        The named run or task does not exist.
    """
    run_user_session_id = _run_user_session_id(connection, request.run_id)
    if run_user_session_id != request.user_session_id:
        raise SessionScopeError(
            f'run {request.run_id!r} does not belong to user session '
            f'{request.user_session_id!r}'
        )
    objective, acceptance_criteria = _task_row(
        connection, request.task_id, request.run_id
    )

    scope = MemorySearchScope(
        project_id=request.project_id, run_id=request.run_id, task_id=request.task_id
    )
    candidates = search_memories(
        connection,
        scope,
        request.query or objective,
        MemoryAccessLog(
            access_id_factory=lambda: str(uuid.uuid4()), created_at=created_at
        ),
    )
    selected, truncated = _select_within_budget(candidates, request.budget_tokens)
    selected_memories = tuple(
        SelectedMemory(
            memory_id=candidate.memory_id,
            title=candidate.title,
            rank=candidate.rank,
            score=candidate.score,
            estimated_tokens=candidate.estimated_tokens,
        )
        for candidate in selected
    )
    estimated_tokens = sum(memory.estimated_tokens for memory in selected_memories)
    stop_conditions = ('memory_budget_exhausted',) if truncated else ()

    digest_payload = json.dumps(
        {
            'task_id': request.task_id,
            'run_id': request.run_id,
            'memories': [memory.memory_id for memory in selected_memories],
            'budget_tokens': request.budget_tokens,
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(digest_payload.encode()).hexdigest()

    return ContextPack(
        task_id=request.task_id,
        project_id=request.project_id,
        run_id=request.run_id,
        user_session_id=request.user_session_id,
        objective=objective,
        acceptance_criteria=acceptance_criteria,
        selected_memories=selected_memories,
        procedure_versions=_active_procedure_versions(connection, request.project_id),
        required_evidence_kinds=REQUIRED_EVIDENCE_KINDS,
        budget_tokens=request.budget_tokens,
        estimated_tokens=estimated_tokens,
        stop_conditions=stop_conditions,
        digest=digest,
    )

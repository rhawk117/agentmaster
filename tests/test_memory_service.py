"""Tests for the memory search/show/lifecycle service (SPEC.md §17.3-§17.5, §23 MT16)."""

import itertools

import pytest
from conftest import SeededMemory, seed_memory, seed_project_run_task

from ledger.memory_service import (
    IllegalMemoryTransitionError,
    MemoryAccessLog,
    MemoryNotFoundError,
    MemorySearchScope,
    NewMemoryInput,
    activate_memory,
    reject_memory,
    search_memories,
    show_memory,
    supersede_memory,
    validate_memory,
)

_CREATED_AT = '2026-07-20T00:00:00Z'
_ids = itertools.count()


def _next_access_id() -> str:
    return f'access-{next(_ids)}'


def _seed_agent_session(connection, agent_session_id):
    connection.execute(
        'INSERT INTO AGENT_SESSION '
        '(id, run_id, role, provider, model, state, started_at) '
        "VALUES (?, 'run-1', 'implementer', 'claude', 'sonnet', 'running', ?)",
        (agent_session_id, _CREATED_AT),
    )
    connection.commit()


def _insert_memory(
    connection,
    memory_id,
    *,
    state,
    title='title',
    content='content',
    proposing_session_id=None,
):
    connection.execute(
        'INSERT INTO MEMORY '
        '(id, origin_project_id, state, memory_kind, title, content, '
        'proposing_session_id, created_at, updated_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            memory_id,
            'project-1',
            state,
            'lesson',
            title,
            content,
            proposing_session_id,
            _CREATED_AT,
            _CREATED_AT,
        ),
    )
    connection.execute(
        'INSERT INTO MEMORY_SCOPE (memory_id, scope_kind, project_id, created_at) '
        "VALUES (?, 'project', 'project-1', ?)",
        (memory_id, _CREATED_AT),
    )
    connection.commit()


@pytest.fixture
def connection(ledger_connection):
    seed_project_run_task(ledger_connection)
    return ledger_connection


@pytest.mark.sqlite
def test_search_memories_returns_ranked_results_and_logs_memory_access(connection):
    seed_memory(
        connection,
        SeededMemory(
            memory_id='memory-1',
            state='Active',
            content='Use jittered backoff for retries',
        ),
    )
    scope = MemorySearchScope(project_id='project-1', run_id='run-1')

    results = search_memories(
        connection,
        scope,
        'backoff',
        MemoryAccessLog(access_id_factory=_next_access_id, created_at=_CREATED_AT),
    )

    assert len(results) == 1
    assert results[0].memory_id == 'memory-1'
    assert results[0].rank == 0
    assert results[0].estimated_tokens > 0
    row = connection.execute(
        'SELECT run_id, memory_id, rank, selected, retrieval_algorithm_version '
        "FROM memory_access WHERE memory_id = 'memory-1'"
    ).fetchone()
    assert row == ('run-1', 'memory-1', 0, 1, 'v1')


@pytest.mark.sqlite
def test_search_memories_excludes_a_candidate_memory(connection):
    seed_memory(
        connection,
        SeededMemory(memory_id='memory-1', state='Candidate', content='backoff jitter'),
    )
    scope = MemorySearchScope(project_id='project-1', run_id='run-1')

    results = search_memories(
        connection,
        scope,
        'backoff',
        MemoryAccessLog(access_id_factory=_next_access_id, created_at=_CREATED_AT),
    )

    assert results == []


@pytest.mark.sqlite
def test_show_memory_returns_none_for_an_unknown_id(connection):
    assert show_memory(connection, 'no-such-memory') is None


@pytest.mark.sqlite
def test_show_memory_returns_the_full_row(connection):
    seed_memory(
        connection,
        SeededMemory(memory_id='memory-1', state='Active', title='Retry backoff'),
    )

    detail = show_memory(connection, 'memory-1')

    assert detail is not None
    assert detail.title == 'Retry backoff'
    assert detail.state == 'Active'


@pytest.mark.sqlite
def test_validate_memory_transitions_candidate_to_validated_and_links_evidence(
    connection,
):
    seed_memory(connection, SeededMemory(memory_id='memory-1', state='Candidate'))
    connection.execute(
        'INSERT INTO ARTIFACT '
        '(id, project_id, sha256, media_type, byte_size, relative_path, retention_class, '
        'redaction_state, created_at) '
        "VALUES ('artifact-1', 'project-1', ?, 'text/plain', 1, 'sha256/x', "
        "'standard', 'redacted', ?)",
        ('x' * 64, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO EVIDENCE (id, run_id, artifact_id, evidence_kind, created_at) '
        "VALUES ('evidence-1', 'run-1', 'artifact-1', 'command-result', ?)",
        (_CREATED_AT,),
    )
    connection.commit()

    validate_memory(connection, 'memory-1', 'evidence-1', updated_at=_CREATED_AT)

    state = connection.execute(
        "SELECT state FROM MEMORY WHERE id = 'memory-1'"
    ).fetchone()[0]
    assert state == 'Validated'
    link = connection.execute(
        "SELECT relation FROM MEMORY_EVIDENCE WHERE memory_id = 'memory-1'"
    ).fetchone()
    assert link == ('validates',)


@pytest.mark.sqlite
def test_validate_memory_refuses_a_validating_session_matching_the_proposer(
    connection,
):
    _seed_agent_session(connection, 'agent-session-1')
    _insert_memory(
        connection,
        'memory-1',
        state='Candidate',
        proposing_session_id='agent-session-1',
    )

    with pytest.raises(IllegalMemoryTransitionError):
        validate_memory(
            connection,
            'memory-1',
            'evidence-1',
            updated_at=_CREATED_AT,
            validating_session_id='agent-session-1',
        )

    state = connection.execute(
        "SELECT state FROM MEMORY WHERE id = 'memory-1'"
    ).fetchone()[0]
    assert state == 'Candidate'


@pytest.mark.sqlite
def test_validate_memory_accepts_a_validating_session_that_differs_from_the_proposer(
    connection,
):
    _seed_agent_session(connection, 'agent-session-1')
    _seed_agent_session(connection, 'agent-session-2')
    _insert_memory(
        connection,
        'memory-1',
        state='Candidate',
        proposing_session_id='agent-session-1',
    )
    connection.execute(
        'INSERT INTO ARTIFACT '
        '(id, project_id, sha256, media_type, byte_size, relative_path, retention_class, '
        'redaction_state, created_at) '
        "VALUES ('artifact-1', 'project-1', ?, 'text/plain', 1, 'sha256/x', "
        "'standard', 'redacted', ?)",
        ('x' * 64, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO EVIDENCE (id, run_id, artifact_id, evidence_kind, created_at) '
        "VALUES ('evidence-1', 'run-1', 'artifact-1', 'command-result', ?)",
        (_CREATED_AT,),
    )
    connection.commit()

    validate_memory(
        connection,
        'memory-1',
        'evidence-1',
        updated_at=_CREATED_AT,
        validating_session_id='agent-session-2',
    )

    state = connection.execute(
        "SELECT state FROM MEMORY WHERE id = 'memory-1'"
    ).fetchone()[0]
    assert state == 'Validated'


@pytest.mark.sqlite
def test_activate_memory_requires_validated_state(connection):
    seed_memory(connection, SeededMemory(memory_id='memory-1', state='Candidate'))

    with pytest.raises(IllegalMemoryTransitionError):
        activate_memory(connection, 'memory-1', updated_at=_CREATED_AT)


@pytest.mark.sqlite
def test_reject_memory_transitions_a_candidate(connection):
    seed_memory(connection, SeededMemory(memory_id='memory-1', state='Candidate'))

    reject_memory(connection, 'memory-1', updated_at=_CREATED_AT)

    state = connection.execute(
        "SELECT state FROM MEMORY WHERE id = 'memory-1'"
    ).fetchone()[0]
    assert state == 'Rejected'


@pytest.mark.sqlite
def test_reject_memory_refuses_an_archived_memory(connection):
    seed_memory(connection, SeededMemory(memory_id='memory-1', state='Archived'))

    with pytest.raises(IllegalMemoryTransitionError):
        reject_memory(connection, 'memory-1', updated_at=_CREATED_AT)


@pytest.mark.sqlite
def test_transition_on_an_unknown_memory_raises_not_found(connection):
    with pytest.raises(MemoryNotFoundError):
        activate_memory(connection, 'no-such-memory', updated_at=_CREATED_AT)


@pytest.mark.sqlite
def test_supersede_memory_creates_a_new_active_memory_and_link(connection):
    seed_memory(
        connection, SeededMemory(memory_id='memory-1', state='Active', title='old title')
    )
    new_memory = NewMemoryInput(
        id='memory-2',
        origin_project_id='project-1',
        memory_kind='lesson',
        title='new title',
        content='new content',
    )

    result_id = supersede_memory(
        connection, 'memory-1', new_memory, updated_at=_CREATED_AT
    )

    assert result_id == 'memory-2'
    old_state = connection.execute(
        "SELECT state FROM MEMORY WHERE id = 'memory-1'"
    ).fetchone()[0]
    assert old_state == 'Superseded'
    new_row = connection.execute(
        "SELECT state, supersedes_memory_id FROM MEMORY WHERE id = 'memory-2'"
    ).fetchone()
    assert new_row == ('Active', 'memory-1')
    link = connection.execute(
        "SELECT link_kind FROM MEMORY_LINK WHERE source_memory_id = 'memory-2' "
        "AND target_memory_id = 'memory-1'"
    ).fetchone()
    assert link == ('supersedes',)
    new_scope = connection.execute(
        "SELECT scope_kind, project_id FROM MEMORY_SCOPE WHERE memory_id = 'memory-2'"
    ).fetchone()
    assert new_scope == ('project', 'project-1')

"""Tests for the bounded, session-scoped context-pack builder (SPEC.md §9.3, §23 MT16)."""

import subprocess
import sys

import pytest

from ledger.connection import connect
from ledger.context_pack import (
    ContextPackRequest,
    RunNotFoundError,
    SessionScopeError,
    TaskNotFoundError,
    build_context_pack,
)
from ledger.migrations import migrate

_CREATED_AT = '2026-07-20T00:00:00Z'


def _seed_project(connection, project_id='project-1'):
    connection.execute(
        'INSERT INTO PROJECT (id, canonical_root, fingerprint, created_at, last_seen_at) '
        'VALUES (?, ?, ?, ?, ?)',
        (project_id, '/repo', f'fp-{project_id}', _CREATED_AT, _CREATED_AT),
    )
    connection.commit()


def _seed_run_and_task(connection, *, acceptance_json=None):
    _seed_project(connection)
    connection.execute(
        'INSERT INTO USER_SESSION (user_session_id, harness_session_id, created_at) '
        "VALUES ('user-session-1', 'harness-1', ?)",
        (_CREATED_AT,),
    )
    connection.execute(
        'INSERT INTO RUN '
        '(id, project_id, user_session_id, delivery_mode, state, started_at) '
        "VALUES ('run-1', 'project-1', 'user-session-1', 'local', 'Planned', ?)",
        (_CREATED_AT,),
    )
    connection.execute(
        'INSERT INTO TASK (id, run_id, title, state, sequence_no, acceptance_json) '
        "VALUES ('task-1', 'run-1', 'retry backoff', 'ready', 1, ?)",
        (acceptance_json,),
    )
    connection.commit()


def _insert_active_memory(connection, memory_id, *, content):
    connection.execute(
        'INSERT INTO MEMORY '
        '(id, origin_project_id, state, memory_kind, title, content, created_at, '
        'updated_at) '
        "VALUES (?, 'project-1', 'Active', 'lesson', 'title', ?, ?, ?)",
        (memory_id, content, _CREATED_AT, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO MEMORY_SCOPE (memory_id, scope_kind, project_id, created_at) '
        "VALUES (?, 'project', 'project-1', ?)",
        (memory_id, _CREATED_AT),
    )
    connection.commit()


@pytest.fixture
def connection(tmp_path):
    conn = connect(tmp_path / 'ledger.sqlite3')
    migrate(conn)
    yield conn
    conn.close()


@pytest.mark.sqlite
def test_build_context_pack_selects_matching_memories_within_budget(connection):
    _seed_run_and_task(connection)
    _insert_active_memory(connection, 'memory-1', content='retry backoff jitter guidance')
    request = ContextPackRequest(
        project_id='project-1',
        user_session_id='user-session-1',
        run_id='run-1',
        task_id='task-1',
        budget_tokens=1000,
    )

    pack = build_context_pack(connection, request, created_at=_CREATED_AT)

    assert pack.task_id == 'task-1'
    assert pack.objective == 'retry backoff'
    assert [m.memory_id for m in pack.selected_memories] == ['memory-1']
    assert pack.estimated_tokens <= pack.budget_tokens
    assert pack.stop_conditions == ()
    assert pack.digest


@pytest.mark.sqlite
def test_build_context_pack_truncates_when_budget_is_exhausted(connection):
    _seed_run_and_task(connection)
    _insert_active_memory(connection, 'memory-1', content='retry backoff jitter guidance')
    request = ContextPackRequest(
        project_id='project-1',
        user_session_id='user-session-1',
        run_id='run-1',
        task_id='task-1',
        budget_tokens=0,
    )

    pack = build_context_pack(connection, request, created_at=_CREATED_AT)

    assert pack.selected_memories == ()
    assert pack.stop_conditions == ('memory_budget_exhausted',)


@pytest.mark.sqlite
def test_build_context_pack_rejects_a_run_outside_the_session(connection):
    _seed_run_and_task(connection)
    request = ContextPackRequest(
        project_id='project-1',
        user_session_id='some-other-session',
        run_id='run-1',
        task_id='task-1',
        budget_tokens=1000,
    )

    with pytest.raises(SessionScopeError):
        build_context_pack(connection, request, created_at=_CREATED_AT)


@pytest.mark.sqlite
def test_build_context_pack_rejects_an_unknown_run(connection):
    request = ContextPackRequest(
        project_id='project-1',
        user_session_id='user-session-1',
        run_id='no-such-run',
        task_id='task-1',
        budget_tokens=1000,
    )

    with pytest.raises(RunNotFoundError):
        build_context_pack(connection, request, created_at=_CREATED_AT)


@pytest.mark.sqlite
def test_build_context_pack_rejects_an_unknown_task(connection):
    _seed_run_and_task(connection)
    request = ContextPackRequest(
        project_id='project-1',
        user_session_id='user-session-1',
        run_id='run-1',
        task_id='no-such-task',
        budget_tokens=1000,
    )

    with pytest.raises(TaskNotFoundError):
        build_context_pack(connection, request, created_at=_CREATED_AT)


@pytest.mark.sqlite
def test_build_context_pack_records_one_memory_access_row_per_candidate(connection):
    _seed_run_and_task(connection)
    _insert_active_memory(connection, 'memory-1', content='retry backoff jitter guidance')
    request = ContextPackRequest(
        project_id='project-1',
        user_session_id='user-session-1',
        run_id='run-1',
        task_id='task-1',
        budget_tokens=1000,
    )

    build_context_pack(connection, request, created_at=_CREATED_AT)

    count = connection.execute(
        "SELECT COUNT(*) FROM memory_access WHERE task_id = 'task-1'"
    ).fetchone()[0]
    assert count == 1


@pytest.mark.subprocess
def test_agentmaster_context_build_subprocess_emits_json(tmp_path, repo_root):
    ledger_path = tmp_path / 'ledger.sqlite3'
    init = subprocess.run(  # noqa: S603
        [
            sys.executable,
            '-m',
            'agentmaster',
            'ledger',
            'init',
            '--path',
            str(ledger_path),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert init.returncode == 0

    connection = connect(ledger_path)
    _seed_run_and_task(connection)
    connection.close()

    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            '-m',
            'agentmaster',
            'context',
            'build',
            '--path',
            str(ledger_path),
            '--project-id',
            'project-1',
            '--user-session-id',
            'user-session-1',
            '--run-id',
            'run-1',
            '--task-id',
            'task-1',
            '--budget-tokens',
            '1000',
            '--json',
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert '"task_id": "task-1"' in result.stdout

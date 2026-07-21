"""Tests for the bounded, session-scoped context-pack builder (SPEC.md §9.3, §23 MT16)."""

import subprocess
import sys

import pytest
from conftest import SeededMemory, seed_memory, seed_project_run_task

from ledger.budget_policy import Budget, bounded_context_pack_tokens
from ledger.connection import connect
from ledger.context_pack import (
    ContextPackRequest,
    RunNotFoundError,
    SessionScopeError,
    TaskNotFoundError,
    build_context_pack,
)

_CREATED_AT = '2026-07-20T00:00:00Z'


@pytest.fixture
def connection(ledger_connection):
    return ledger_connection


@pytest.mark.sqlite
def test_build_context_pack_selects_matching_memories_within_budget(connection):
    seed_project_run_task(connection)
    seed_memory(
        connection,
        SeededMemory(memory_id='memory-1', content='retry backoff jitter guidance'),
    )
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
    seed_project_run_task(connection)
    seed_memory(
        connection,
        SeededMemory(memory_id='memory-1', content='retry backoff jitter guidance'),
    )
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
def test_build_context_pack_honors_a_budget_capped_by_bounded_context_pack_tokens(
    connection,
):
    seed_project_run_task(connection)
    seed_memory(
        connection,
        SeededMemory(memory_id='memory-1', content='retry backoff jitter guidance'),
    )
    budget = Budget(
        token_budget=10_000,
        cost_micro_usd_budget=10_000,
        duration_ms_budget=10_000,
        parallelism_budget=1,
        context_pack_token_budget=5,
    )
    requested_tokens = bounded_context_pack_tokens(budget, requested_tokens=1_000)
    request = ContextPackRequest(
        project_id='project-1',
        user_session_id='user-session-1',
        run_id='run-1',
        task_id='task-1',
        budget_tokens=requested_tokens,
    )

    pack = build_context_pack(connection, request, created_at=_CREATED_AT)

    assert requested_tokens == 5
    assert pack.budget_tokens == 5
    assert pack.estimated_tokens <= 5


@pytest.mark.sqlite
def test_build_context_pack_rejects_a_run_outside_the_session(connection):
    seed_project_run_task(connection)
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
    seed_project_run_task(connection)
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
    seed_project_run_task(connection)
    seed_memory(
        connection,
        SeededMemory(memory_id='memory-1', content='retry backoff jitter guidance'),
    )
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
    seed_project_run_task(connection)
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

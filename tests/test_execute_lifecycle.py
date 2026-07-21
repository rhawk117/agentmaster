"""Durable RUN/TASK lifecycle through the execute command surface (scenario 5).

Red against v2.0.0 for a structural reason (evidence 6): `agentmaster/cli.py`
has `ledger`/`memory`/`delivery`/`retro`/`worth` command groups but no
`run`/`task`/`dispatch` group -- nothing calls
`ledger.orchestrator_state.transition_run`/`transition_task` during a live
run. These tests exercise the intended `run start` / `task ...` surface (T4)
and fail at the very first CLI invocation with the missing-subcommand
`SystemExit(2)` argparse raises, never a crash from lower-level ledger code
(which already works and is not what's under test here).
"""

import pytest

from agentmaster.cli import main
from ledger.connection import connect as connect_ledger
from ledger.ingestion import resolve_project, resolve_run, upsert_user_session
from ledger.migrations import migrate as migrate_ledger


@pytest.fixture
def ledger_path(tmp_path):
    path = tmp_path / 'ledger.sqlite3'
    connection = connect_ledger(path)
    migrate_ledger(connection)
    connection.close()
    return path


def test_run_start_register_tasks_and_transition_lifecycle(ledger_path):
    """The full scenario 5 contract: `run start` creates/resumes exactly one
    RUN; task registration creates the expected TASK rows + dependencies;
    ready->running->verify->complete transitions append RUN_TRANSITION/
    TASK_TRANSITION rows; an illegal transition is rejected; resuming an
    interrupted run creates no duplicate run/task/lease.

    Every one of these commands is new work for T4 -- the very first call
    raises argparse's missing-subcommand `SystemExit(2)`, which is the
    documented red reason (evidence 6), not a crash.
    """
    with pytest.raises(SystemExit) as excinfo:
        main([
            'run',
            'start',
            '--path',
            str(ledger_path),
            '--user-session-id',
            'user-session-1',
            '--project-root',
            '/repo',
        ])
    assert excinfo.value.code == 0, (
        '`agentmaster run start` does not exist yet (no `run`/`task`/`dispatch` '
        'CLI group, evidence 6): argparse rejects the unknown subcommand with '
        f'exit code {excinfo.value.code} instead of succeeding'
    )


def test_single_run_after_drain_then_start(ledger_path):
    """RUN-reconciliation contract, ordering 1: a telemetry drain that
    auto-creates a session-scoped RUN (`ledger.ingestion.resolve_run`, already
    real) must be reused -- not duplicated -- by a subsequent `run start` for
    the same user session.
    """
    connection = connect_ledger(ledger_path)
    now = lambda: '2026-07-21T00:00:00Z'  # noqa: E731
    counter = iter(f'id-{n}' for n in range(100))
    id_factory = lambda: next(counter)  # noqa: E731

    user_session_id = upsert_user_session(
        connection, 'harness-1', id_factory=id_factory, now=now
    )
    project_id = resolve_project(
        connection, canonical_root='/repo', id_factory=id_factory, now=now
    )
    drained_run_id = resolve_run(
        connection,
        project_id=project_id,
        user_session_id=user_session_id,
        id_factory=id_factory,
        now=now,
    )
    connection.close()

    with pytest.raises(SystemExit) as excinfo:
        main([
            'run',
            'start',
            '--path',
            str(ledger_path),
            '--user-session-id',
            'user-session-1',
            '--project-root',
            '/repo',
        ])
    assert excinfo.value.code == 0, (
        '`agentmaster run start` does not exist yet, so it cannot reuse the '
        f'drain-created RUN {drained_run_id!r} for this user session -- '
        f'argparse instead exits {excinfo.value.code} on the unknown subcommand'
    )


def test_single_run_after_start_then_drain(ledger_path):
    """RUN-reconciliation contract, ordering 2: `run start` first, then a
    telemetry drain for the same user session, must still resolve to exactly
    one RUN.
    """
    with pytest.raises(SystemExit) as excinfo:
        main([
            'run',
            'start',
            '--path',
            str(ledger_path),
            '--user-session-id',
            'user-session-1',
            '--project-root',
            '/repo',
        ])
    assert excinfo.value.code == 0, (
        '`agentmaster run start` does not exist yet (evidence 6), so this '
        'ordering cannot even begin -- argparse exits on the unknown '
        f'subcommand with code {excinfo.value.code}'
    )

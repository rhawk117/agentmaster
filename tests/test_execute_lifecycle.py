"""Durable RUN/TASK lifecycle through the execute command surface (scenario 5).

`agentmaster/cli.py` now has a `run`/`task`/`dispatch` command group backed by
`ledger.orchestrator_state.transition_run`/`transition_task`. These tests drive
that real surface end to end and assert against the ledger DB directly: RUN/TASK
rows, appended RUN_TRANSITION/TASK_TRANSITION rows, illegal-transition rejection,
and the RUN-reconciliation contract (exactly one RUN per user session,
regardless of whether `run start` or a telemetry drain runs first).
"""

import json

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


@pytest.fixture
def project_root(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    return root


def test_run_start_register_tasks_and_transition_lifecycle(
    ledger_path, project_root, capsys
):
    """`run start` creates one RUN; task registration creates the expected
    TASK rows + dependency; ready->running->review-required->complete and
    Planned->Preflight->Executing->Verifying transitions append
    RUN_TRANSITION/TASK_TRANSITION rows; an illegal transition on either is
    rejected (non-zero, JSON `error` key, no state change).
    """
    assert (
        main([
            'run',
            'start',
            '--path',
            str(ledger_path),
            '--user-session-id',
            'harness-1',
            '--project-root',
            str(project_root),
        ])
        == 0
    )
    run_payload = json.loads(capsys.readouterr().out)
    run_id = run_payload['run_id']
    assert run_payload['created'] is True

    assert (
        main([
            'task',
            'register',
            '--path',
            str(ledger_path),
            '--run-id',
            run_id,
            '--task-id',
            'task-1',
            '--title',
            'first task',
            '--sequence-no',
            '1',
        ])
        == 0
    )
    task1_id = json.loads(capsys.readouterr().out)['task_id']
    assert task1_id == 'task-1'

    assert (
        main([
            'task',
            'register',
            '--path',
            str(ledger_path),
            '--run-id',
            run_id,
            '--task-id',
            'task-2',
            '--title',
            'second task',
            '--sequence-no',
            '2',
            '--depends-on',
            f'{task1_id}=blocks',
        ])
        == 0
    )
    task2_id = json.loads(capsys.readouterr().out)['task_id']

    connection = connect_ledger(ledger_path)
    try:
        user_session_id = connection.execute(
            'SELECT user_session_id FROM USER_SESSION WHERE harness_session_id = ?',
            ('harness-1',),
        ).fetchone()[0]
        assert (
            connection.execute(
                'SELECT COUNT(*) FROM RUN WHERE user_session_id = ?',
                (user_session_id,),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                'SELECT COUNT(*) FROM TASK WHERE run_id = ?', (run_id,)
            ).fetchone()[0]
            == 2
        )
        assert (
            connection.execute(
                'SELECT dependency_kind FROM TASK_DEPENDENCY '
                'WHERE task_id = ? AND depends_on_task_id = ?',
                (task2_id, task1_id),
            ).fetchone()[0]
            == 'blocks'
        )
    finally:
        connection.close()

    for to_state in ('Preflight', 'Executing', 'Verifying'):
        assert (
            main([
                'run',
                'transition',
                '--path',
                str(ledger_path),
                '--run-id',
                run_id,
                '--to-state',
                to_state,
            ])
            == 0
        )
        capsys.readouterr()

    for to_state in ('running', 'review-required', 'complete'):
        assert (
            main([
                'task',
                'transition',
                '--path',
                str(ledger_path),
                '--task-id',
                task1_id,
                '--to-state',
                to_state,
            ])
            == 0
        )
        capsys.readouterr()

    connection = connect_ledger(ledger_path)
    try:
        assert (
            connection.execute(
                'SELECT COUNT(*) FROM RUN_TRANSITION WHERE run_id = ?', (run_id,)
            ).fetchone()[0]
            == 3
        )
        assert (
            connection.execute(
                'SELECT COUNT(*) FROM TASK_TRANSITION WHERE task_id = ?', (task1_id,)
            ).fetchone()[0]
            == 3
        )
        assert (
            connection.execute(
                'SELECT state FROM TASK WHERE id = ?', (task1_id,)
            ).fetchone()[0]
            == 'complete'
        )
        assert (
            connection.execute(
                'SELECT state FROM RUN WHERE id = ?', (run_id,)
            ).fetchone()[0]
            == 'Verifying'
        )
    finally:
        connection.close()

    # Illegal TASK transition: task2 is still 'ready'; ready -> complete is
    # not in TASK_TRANSITIONS['ready'].
    exit_code = main([
        'task',
        'transition',
        '--path',
        str(ledger_path),
        '--task-id',
        task2_id,
        '--to-state',
        'complete',
    ])
    error_payload = json.loads(capsys.readouterr().out)
    assert exit_code != 0
    assert 'error' in error_payload

    # Illegal RUN transition: Verifying -> Complete is not in
    # RUN_TRANSITIONS['Verifying'] (only FixesRequired/DeliveryPending/
    # Failed/Cancelled).
    exit_code = main([
        'run',
        'transition',
        '--path',
        str(ledger_path),
        '--run-id',
        run_id,
        '--to-state',
        'Complete',
    ])
    error_payload = json.loads(capsys.readouterr().out)
    assert exit_code != 0
    assert 'error' in error_payload

    connection = connect_ledger(ledger_path)
    try:
        assert (
            connection.execute(
                'SELECT state FROM TASK WHERE id = ?', (task2_id,)
            ).fetchone()[0]
            == 'ready'
        )
        assert (
            connection.execute(
                'SELECT state FROM RUN WHERE id = ?', (run_id,)
            ).fetchone()[0]
            == 'Verifying'
        )
    finally:
        connection.close()


def test_single_run_after_drain_then_start(ledger_path, project_root, capsys):
    """RUN-reconciliation contract, ordering 1: a telemetry drain that
    auto-creates a session-scoped RUN (`ledger.ingestion.resolve_run`) must be
    reused -- not duplicated -- by a subsequent `run start` for the same user
    session. Asserted directly against the ledger DB: exactly one RUN row.
    """
    now = lambda: '2026-07-21T00:00:00Z'  # noqa: E731
    counter = iter(f'id-{n}' for n in range(100))
    id_factory = lambda: next(counter)  # noqa: E731

    connection = connect_ledger(ledger_path)
    user_session_id = upsert_user_session(
        connection, 'harness-1', id_factory=id_factory, now=now
    )
    project_id = resolve_project(
        connection, canonical_root=str(project_root), id_factory=id_factory, now=now
    )
    drained_run_id = resolve_run(
        connection,
        project_id=project_id,
        user_session_id=user_session_id,
        id_factory=id_factory,
        now=now,
    )
    connection.close()

    assert (
        main([
            'run',
            'start',
            '--path',
            str(ledger_path),
            '--user-session-id',
            'harness-1',
            '--project-root',
            str(project_root),
        ])
        == 0
    )
    run_payload = json.loads(capsys.readouterr().out)
    assert run_payload['run_id'] == drained_run_id
    assert run_payload['created'] is False

    connection = connect_ledger(ledger_path)
    try:
        assert (
            connection.execute(
                'SELECT COUNT(*) FROM RUN WHERE user_session_id = ?',
                (user_session_id,),
            ).fetchone()[0]
            == 1
        )
    finally:
        connection.close()


def _start_run(ledger_path, project_root, capsys, harness_session_id='harness-1'):
    assert (
        main([
            'run',
            'start',
            '--path',
            str(ledger_path),
            '--user-session-id',
            harness_session_id,
            '--project-root',
            str(project_root),
        ])
        == 0
    )
    return json.loads(capsys.readouterr().out)['run_id']


def test_depends_on_resolves_default_colon_bearing_task_id(
    ledger_path, project_root, capsys
):
    """A dependency declared against a DEFAULT auto-generated task id (which
    itself contains colons, `task:{run_id}:{sequence_no}`) must create the
    correct `TASK_DEPENDENCY` row -- `--depends-on`'s `=`-delimited kind must
    not be confused by colons inside the referenced task id.
    """
    run_id = _start_run(ledger_path, project_root, capsys)

    assert (
        main([
            'task',
            'register',
            '--path',
            str(ledger_path),
            '--run-id',
            run_id,
            '--title',
            'first task',
            '--sequence-no',
            '1',
        ])
        == 0
    )
    task1_id = json.loads(capsys.readouterr().out)['task_id']
    assert task1_id == f'task:{run_id}:1'

    assert (
        main([
            'task',
            'register',
            '--path',
            str(ledger_path),
            '--run-id',
            run_id,
            '--title',
            'second task',
            '--sequence-no',
            '2',
            '--depends-on',
            task1_id,
        ])
        == 0
    )
    task2_id = json.loads(capsys.readouterr().out)['task_id']

    connection = connect_ledger(ledger_path)
    try:
        row = connection.execute(
            'SELECT depends_on_task_id, dependency_kind FROM TASK_DEPENDENCY '
            'WHERE task_id = ?',
            (task2_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row == (task1_id, 'blocks')


def test_depends_on_missing_task_fails_closed(ledger_path, project_root, capsys):
    """A `--depends-on` referencing a task that does not exist must fail
    loud -- non-zero exit, JSON `error` -- not be silently dropped by the
    `INSERT OR IGNORE` (which also swallows foreign-key violations).
    """
    run_id = _start_run(ledger_path, project_root, capsys)

    exit_code = main([
        'task',
        'register',
        '--path',
        str(ledger_path),
        '--run-id',
        run_id,
        '--task-id',
        'task-1',
        '--title',
        'first task',
        '--sequence-no',
        '1',
        '--depends-on',
        'task-does-not-exist',
    ])
    error_payload = json.loads(capsys.readouterr().out)
    assert exit_code != 0
    assert 'error' in error_payload

    connection = connect_ledger(ledger_path)
    try:
        assert (
            connection.execute('SELECT COUNT(*) FROM TASK_DEPENDENCY').fetchone()[0] == 0
        )
    finally:
        connection.close()


def test_depends_on_redeclaring_same_dependency_is_idempotent(
    ledger_path, project_root, capsys
):
    """Re-registering the SAME valid `--depends-on` edge must stay
    idempotent -- no duplicate `TASK_DEPENDENCY` row.
    """
    run_id = _start_run(ledger_path, project_root, capsys)

    assert (
        main([
            'task',
            'register',
            '--path',
            str(ledger_path),
            '--run-id',
            run_id,
            '--task-id',
            'task-1',
            '--title',
            'first task',
            '--sequence-no',
            '1',
        ])
        == 0
    )
    capsys.readouterr()

    for _ in range(2):
        assert (
            main([
                'task',
                'register',
                '--path',
                str(ledger_path),
                '--run-id',
                run_id,
                '--task-id',
                'task-2',
                '--title',
                'second task',
                '--sequence-no',
                '2',
                '--depends-on',
                'task-1=blocks',
            ])
            == 0
        )
        capsys.readouterr()

    connection = connect_ledger(ledger_path)
    try:
        assert (
            connection.execute(
                'SELECT COUNT(*) FROM TASK_DEPENDENCY WHERE task_id = ?',
                ('task-2',),
            ).fetchone()[0]
            == 1
        )
    finally:
        connection.close()


def test_run_id_marker_retires_on_terminal_completion(ledger_path, project_root, capsys):
    """T5: once a RUN reaches a `RUN_TERMINAL_STATES` state, its session-scoped
    `.run_id` marker must be removed so a later session (e.g. the Stop hook)
    never blocks on a run that has already finished/failed/been cancelled.
    """
    assert (
        main([
            'run',
            'start',
            '--path',
            str(ledger_path),
            '--user-session-id',
            'harness-1',
            '--project-root',
            str(project_root),
        ])
        == 0
    )
    run_id = json.loads(capsys.readouterr().out)['run_id']

    marker = project_root / '.agentmaster' / 'sessions' / 'harness-1' / '.run_id'
    assert marker.is_file()
    assert marker.read_text(encoding='utf-8') == run_id

    assert (
        main([
            'run',
            'transition',
            '--path',
            str(ledger_path),
            '--run-id',
            run_id,
            '--to-state',
            'Cancelled',
        ])
        == 0
    )
    capsys.readouterr()

    assert not marker.exists(), (
        'a RUN reaching a terminal state (Cancelled) must retire its .run_id '
        'marker, not leave it pointing at a finished run'
    )


def test_run_id_marker_untouched_by_a_non_terminal_transition(
    ledger_path, project_root, capsys
):
    """Only a genuinely terminal transition retires the marker -- an
    in-flight run must keep blocking a later Stop until it actually finishes.
    """
    assert (
        main([
            'run',
            'start',
            '--path',
            str(ledger_path),
            '--user-session-id',
            'harness-1',
            '--project-root',
            str(project_root),
        ])
        == 0
    )
    run_id = json.loads(capsys.readouterr().out)['run_id']
    marker = project_root / '.agentmaster' / 'sessions' / 'harness-1' / '.run_id'

    assert (
        main([
            'run',
            'transition',
            '--path',
            str(ledger_path),
            '--run-id',
            run_id,
            '--to-state',
            'Preflight',
        ])
        == 0
    )
    capsys.readouterr()

    assert marker.is_file()
    assert marker.read_text(encoding='utf-8') == run_id


def test_single_run_after_start_then_drain(ledger_path, project_root, capsys):
    """RUN-reconciliation contract, ordering 2: `run start` first, then a
    telemetry drain (`ledger.ingestion.resolve_run`) for the same user
    session, must still resolve to exactly one RUN row.
    """
    assert (
        main([
            'run',
            'start',
            '--path',
            str(ledger_path),
            '--user-session-id',
            'harness-1',
            '--project-root',
            str(project_root),
        ])
        == 0
    )
    started_run_id = json.loads(capsys.readouterr().out)['run_id']

    now = lambda: '2026-07-21T00:00:00Z'  # noqa: E731
    counter = iter(f'id-{n}' for n in range(100))
    id_factory = lambda: next(counter)  # noqa: E731

    connection = connect_ledger(ledger_path)
    user_session_id = connection.execute(
        'SELECT user_session_id FROM USER_SESSION WHERE harness_session_id = ?',
        ('harness-1',),
    ).fetchone()[0]
    project_id = connection.execute(
        'SELECT project_id FROM RUN WHERE id = ?', (started_run_id,)
    ).fetchone()[0]
    drained_run_id = resolve_run(
        connection,
        project_id=project_id,
        user_session_id=user_session_id,
        id_factory=id_factory,
        now=now,
    )
    connection.close()

    assert drained_run_id == started_run_id

    connection = connect_ledger(ledger_path)
    try:
        assert (
            connection.execute(
                'SELECT COUNT(*) FROM RUN WHERE user_session_id = ?',
                (user_session_id,),
            ).fetchone()[0]
            == 1
        )
    finally:
        connection.close()

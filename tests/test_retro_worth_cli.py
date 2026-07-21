"""Tests for the `agentmaster retro`/`agentmaster worth` CLI wiring (SPEC.md §19)."""

import pytest
from conftest import seed_project_run_task

from agentmaster.cli import main
from ledger.connection import connect

_CREATED_AT = '2026-07-20T00:00:00Z'


@pytest.fixture
def ledger_path(tmp_path):
    path = tmp_path / 'ledger.sqlite3'
    assert main(['ledger', 'init', '--path', str(path)]) == 0
    return path


@pytest.mark.sqlite
def test_retro_run_rejects_a_run_not_yet_retrospective_pending(capsys, ledger_path):
    connection = connect(ledger_path)
    seed_project_run_task(connection)
    connection.close()

    exit_code = main(['retro', 'run', '--path', str(ledger_path), '--run-id', 'run-1'])

    assert exit_code == 1
    assert 'retro run' in capsys.readouterr().err


@pytest.mark.sqlite
def test_retro_run_then_show_round_trip(capsys, ledger_path):
    connection = connect(ledger_path)
    seed_project_run_task(connection)
    connection.execute("UPDATE RUN SET state = 'RetrospectivePending' WHERE id = 'run-1'")
    connection.commit()
    connection.close()

    run_exit_code = main([
        'retro',
        'run',
        '--path',
        str(ledger_path),
        '--run-id',
        'run-1',
        '--json',
    ])
    capsys.readouterr()
    show_exit_code = main([
        'retro',
        'show',
        '--path',
        str(ledger_path),
        '--run-id',
        'run-1',
        '--json',
    ])

    assert (run_exit_code, show_exit_code) == (0, 0)
    connection = connect(ledger_path)
    (state,) = connection.execute("SELECT state FROM RUN WHERE id = 'run-1'").fetchone()
    connection.close()
    assert state == 'Complete'


@pytest.mark.sqlite
def test_retro_show_reports_no_retrospective_for_an_unstarted_run(capsys, ledger_path):
    connection = connect(ledger_path)
    seed_project_run_task(connection)
    connection.close()

    exit_code = main(['retro', 'show', '--path', str(ledger_path), '--run-id', 'run-1'])

    assert exit_code == 1
    assert 'no retrospective' in capsys.readouterr().err


@pytest.mark.sqlite
def test_retro_propose_creates_a_project_scoped_candidate(capsys, ledger_path):
    connection = connect(ledger_path)
    seed_project_run_task(connection)
    connection.execute(
        'INSERT INTO RETROSPECTIVE (id, run_id, status, created_at) '
        "VALUES ('retro-1', 'run-1', 'Complete', ?)",
        (_CREATED_AT,),
    )
    connection.execute(
        'INSERT INTO RETRO_OBSERVATION '
        '(id, retrospective_id, observation_kind, claim, created_at) '
        "VALUES ('obs-1', 'retro-1', 'outcome', 'claim', ?)",
        (_CREATED_AT,),
    )
    connection.execute(
        'INSERT INTO ARTIFACT (id, project_id, sha256, media_type, byte_size, '
        'relative_path, retention_class, redaction_state, created_at) '
        "VALUES ('artifact-1', 'project-1', 'sha', 'text/plain', 1, 'p', "
        "'standard', 'clean', ?)",
        (_CREATED_AT,),
    )
    connection.execute(
        'INSERT INTO EVIDENCE (id, run_id, artifact_id, evidence_kind, created_at) '
        "VALUES ('evidence-1', 'run-1', 'artifact-1', 'command-result', ?)",
        (_CREATED_AT,),
    )
    connection.commit()
    connection.close()

    exit_code = main([
        'retro',
        'propose',
        '--path',
        str(ledger_path),
        '--memory-id',
        'memory-1',
        '--project-id',
        'project-1',
        '--memory-kind',
        'lesson',
        '--title',
        'title',
        '--content',
        'content',
        '--observation-id',
        'obs-1',
        '--evidence-id',
        'evidence-1',
    ])

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == 'memory-1'
    connection = connect(ledger_path)
    state = connection.execute(
        "SELECT state FROM MEMORY WHERE id = 'memory-1'"
    ).fetchone()[0]
    connection.close()
    assert state == 'Candidate'


@pytest.mark.sqlite
def test_worth_run_on_an_unknown_run_fails(capsys, ledger_path):
    exit_code = main([
        'worth',
        'run',
        '--path',
        str(ledger_path),
        '--run-id',
        'no-such-run',
    ])

    assert exit_code == 1
    assert 'worth run' in capsys.readouterr().err


@pytest.mark.sqlite
def test_worth_run_reports_task_and_token_totals(capsys, ledger_path):
    connection = connect(ledger_path)
    seed_project_run_task(connection)
    connection.close()

    exit_code = main(['worth', 'run', '--path', str(ledger_path), '--run-id', 'run-1'])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert 'run-1' in out


@pytest.mark.sqlite
def test_worth_memory_reports_zero_counts_for_an_unretrieved_memory(capsys, ledger_path):
    connection = connect(ledger_path)
    seed_project_run_task(connection)
    connection.execute(
        'INSERT INTO MEMORY (id, origin_project_id, state, memory_kind, title, '
        'content, created_at, updated_at) '
        "VALUES ('memory-1', 'project-1', 'Active', 'lesson', 'title', 'content', "
        '?, ?)',
        (_CREATED_AT, _CREATED_AT),
    )
    connection.commit()
    connection.close()

    exit_code = main([
        'worth',
        'memory',
        '--path',
        str(ledger_path),
        '--memory-id',
        'memory-1',
    ])

    assert exit_code == 0
    assert 'retrievals=0' in capsys.readouterr().out


@pytest.mark.sqlite
def test_worth_procedure_reports_zero_uses_for_a_fresh_procedure(capsys, ledger_path):
    connection = connect(ledger_path)
    seed_project_run_task(connection)
    connection.execute(
        'INSERT INTO PROCEDURE (id, project_id, name, scope, state, created_at) '
        "VALUES ('procedure-1', 'project-1', 'name', 'skill', 'active', ?)",
        (_CREATED_AT,),
    )
    connection.commit()
    connection.close()

    exit_code = main([
        'worth',
        'procedure',
        '--path',
        str(ledger_path),
        '--procedure-id',
        'procedure-1',
    ])

    assert exit_code == 0
    assert 'uses=0' in capsys.readouterr().out

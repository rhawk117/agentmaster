import json

import pytest
from conftest import SeededMemory, seed_memory, seed_project_run_task

from agentmaster.cli import main
from ledger.connection import connect

_CREATED_AT = '2026-07-20T00:00:00Z'


@pytest.fixture
def ledger_path(tmp_path):
    path = tmp_path / 'ledger.sqlite3'
    assert main(['ledger', 'init', '--path', str(path)]) == 0
    return path


@pytest.mark.sqlite
def test_ledger_record_feedback_then_query_round_trip(capsys, ledger_path):
    connection = connect(ledger_path)
    seed_project_run_task(connection)
    connection.close()

    exit_code = main([
        'ledger',
        'record-feedback',
        '--path',
        str(ledger_path),
        '--user-session-id',
        'user-session-1',
        '--run-id',
        'run-1',
        '--rating',
        '1',
    ])

    assert exit_code == 0
    feedback_id = capsys.readouterr().out.strip()
    connection = connect(ledger_path)
    row = connection.execute(
        'SELECT rating FROM FEEDBACK WHERE id = ?', (feedback_id,)
    ).fetchone()
    connection.close()
    assert row == (1,)


@pytest.mark.sqlite
def test_ledger_record_feedback_rejects_an_unknown_run(capsys, ledger_path):
    exit_code = main([
        'ledger',
        'record-feedback',
        '--path',
        str(ledger_path),
        '--user-session-id',
        'user-session-1',
        '--run-id',
        'no-such-run',
        '--rating',
        '0',
    ])

    assert exit_code == 1
    assert 'does not exist' in capsys.readouterr().err


@pytest.mark.sqlite
def test_ledger_query_entrypoints_on_a_fresh_ledger_reports_empty(capsys, ledger_path):
    exit_code = main([
        'ledger',
        'query',
        'entrypoints',
        '--path',
        str(ledger_path),
        '--json',
    ])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == []


@pytest.mark.sqlite
def test_ledger_query_runs_on_a_fresh_ledger_reports_empty(capsys, ledger_path):
    exit_code = main(['ledger', 'query', 'runs', '--path', str(ledger_path), '--json'])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == []


@pytest.mark.sqlite
def test_ledger_query_tokens_on_a_fresh_ledger_reports_empty(capsys, ledger_path):
    exit_code = main(['ledger', 'query', 'tokens', '--path', str(ledger_path), '--json'])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == []


@pytest.mark.sqlite
def test_ledger_ingest_events_drains_the_spool(capsys, tmp_path, ledger_path):
    spool = tmp_path / 'events'
    spool.mkdir()
    (spool / '1.json').write_text(
        json.dumps({
            'schema_version': 1,
            'kind': 'agent_session',
            'harness_session_id': 'harness-1',
            'cwd': '/repo',
            'agent_id': 'agent-1',
            'role': 'scout',
            'model': 'haiku',
            'total_tokens': 5,
            'duration_ms': 10,
        }),
        encoding='utf-8',
    )

    exit_code = main([
        'ledger',
        'ingest-events',
        '--path',
        str(ledger_path),
        '--spool',
        str(spool),
        '--json',
    ])

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report == {'ingested': 1, 'malformed': 0, 'unsupported': 0, 'failed': 0}
    assert list(spool.glob('*.json')) == []

    connection = connect(ledger_path)
    run_count = connection.execute('SELECT COUNT(*) FROM RUN').fetchone()[0]
    connection.close()
    assert run_count == 1


@pytest.mark.sqlite
def test_migrate_legacy_files_dry_run_then_apply(capsys, tmp_path, ledger_path):
    workspace = tmp_path / 'workspace'
    am = workspace / '.agentmaster'
    am.mkdir(parents=True)
    (am / 'telemetry.md').write_text('hook,scout,haiku,42,100\n')

    exit_code = main([
        'migrate',
        'legacy-files',
        '--path',
        str(ledger_path),
        '--workspace',
        str(workspace),
        '--dry-run',
        '--json',
    ])
    assert exit_code == 0
    dry_run_report = json.loads(capsys.readouterr().out)
    assert dry_run_report[0]['imported'] == 1
    assert dry_run_report[0]['artifact_id'] is None

    connection = connect(ledger_path)
    assert connection.execute('SELECT COUNT(*) FROM RUN').fetchone()[0] == 0
    connection.close()

    exit_code = main([
        'migrate',
        'legacy-files',
        '--path',
        str(ledger_path),
        '--workspace',
        str(workspace),
        '--json',
    ])
    assert exit_code == 0
    apply_report = json.loads(capsys.readouterr().out)
    assert apply_report[0]['imported'] == 1
    assert apply_report[0]['artifact_id'] is not None

    connection = connect(ledger_path)
    assert connection.execute('SELECT COUNT(*) FROM MODEL_CALL').fetchone()[0] == 1
    connection.close()
    assert (am / 'telemetry.md').is_file()


@pytest.mark.sqlite
def test_memory_lifecycle_via_cli(capsys, ledger_path):
    connection = connect(ledger_path)
    seed_project_run_task(connection)
    seed_memory(connection, SeededMemory(memory_id='memory-1', state='Candidate'))
    connection.close()

    exit_code = main([
        'memory',
        'reject',
        '--path',
        str(ledger_path),
        '--memory-id',
        'memory-1',
    ])
    assert exit_code == 0

    exit_code = main([
        'memory',
        'show',
        '--path',
        str(ledger_path),
        '--memory-id',
        'memory-1',
        '--json',
    ])
    assert exit_code == 0
    detail = json.loads(capsys.readouterr().out)
    assert detail['state'] == 'Rejected'


@pytest.mark.sqlite
def test_memory_validate_rejects_the_proposing_session_via_cli(capsys, ledger_path):
    connection = connect(ledger_path)
    seed_project_run_task(connection)
    connection.execute(
        'INSERT INTO AGENT_SESSION '
        '(id, run_id, role, provider, model, state, started_at) '
        "VALUES ('agent-session-1', 'run-1', 'implementer', 'claude', 'sonnet', "
        "'running', ?)",
        (_CREATED_AT,),
    )
    connection.execute(
        'INSERT INTO MEMORY '
        '(id, origin_project_id, state, memory_kind, title, content, '
        'proposing_session_id, created_at, updated_at) '
        "VALUES ('memory-1', 'project-1', 'Candidate', 'lesson', 'title', 'content', "
        "'agent-session-1', ?, ?)",
        (_CREATED_AT, _CREATED_AT),
    )
    connection.commit()
    connection.close()

    exit_code = main([
        'memory',
        'validate',
        '--path',
        str(ledger_path),
        '--memory-id',
        'memory-1',
        '--evidence-id',
        'evidence-1',
        '--validating-session-id',
        'agent-session-1',
    ])

    assert exit_code == 1
    assert 'must differ from the proposing session' in capsys.readouterr().err
    connection = connect(ledger_path)
    state = connection.execute(
        "SELECT state FROM MEMORY WHERE id = 'memory-1'"
    ).fetchone()[0]
    connection.close()
    assert state == 'Candidate'


@pytest.mark.sqlite
def test_memory_show_on_an_unknown_id_fails(capsys, ledger_path):
    exit_code = main([
        'memory',
        'show',
        '--path',
        str(ledger_path),
        '--memory-id',
        'no-such-memory',
    ])

    assert exit_code == 1
    assert 'not found' in capsys.readouterr().err


def test_context_route_sends_a_risky_task_to_stronger_review(capsys):
    exit_code = main(['context', 'route', '--auth', '--json'])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['route'] == 'stronger_review'
    assert payload['risk_level'] == 'high'
    assert 'auth' in payload['risk_factors']


def test_context_route_sends_an_ambiguous_only_task_to_a_coordinator_scout(capsys):
    exit_code = main(['context', 'route', '--ambiguous', '--json'])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['route'] == 'coordinator_scout'


def test_context_route_sends_a_plain_task_to_the_implementer(capsys):
    exit_code = main(['context', 'route', '--json'])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['route'] == 'implementer'
    assert payload['risk_level'] == 'routine'


def test_context_route_includes_scout_authorization_when_scouts_are_requested(capsys):
    exit_code = main([
        'context',
        'route',
        '--ambiguous',
        '--requested-scouts',
        '1',
        '--implementer-scout-enabled',
        '--implementer-scout-budget-tokens',
        '500',
        '--json',
    ])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['scout_authorization']['authorized'] is True
    assert payload['scout_authorization']['budget_tokens'] == 500

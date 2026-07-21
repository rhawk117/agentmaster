"""Tests for `ledger.ingestion` (SPEC.md §16.3, §17, §19, §23 Microtask 17)."""

import itertools
import json

import pytest

from ledger.event_spool import read_events
from ledger.ingestion import ingest_pending_events, resolve_project, upsert_user_session

_CREATED_AT = '2026-07-20T00:00:00Z'


def _now() -> str:
    return _CREATED_AT


def _id_factory():
    counter = itertools.count(1)

    def _next() -> str:
        return f'id-{next(counter)}'

    return _next


def _write_event(spool_dir, name, record):
    spool_dir.mkdir(parents=True, exist_ok=True)
    (spool_dir / name).write_text(json.dumps(record), encoding='utf-8')


@pytest.mark.sqlite
def test_upsert_user_session_is_idempotent(ledger_connection):
    ids = _id_factory()

    first = upsert_user_session(ledger_connection, 'harness-1', id_factory=ids, now=_now)
    second = upsert_user_session(ledger_connection, 'harness-1', id_factory=ids, now=_now)

    assert first == second
    rows = ledger_connection.execute(
        'SELECT COUNT(*) FROM USER_SESSION WHERE harness_session_id = ?', ('harness-1',)
    ).fetchone()
    assert rows[0] == 1


@pytest.mark.sqlite
def test_resolve_project_reuses_row_for_same_canonical_root(ledger_connection):
    ids = _id_factory()

    first = resolve_project(
        ledger_connection, canonical_root='/repo', id_factory=ids, now=_now
    )
    second = resolve_project(
        ledger_connection, canonical_root='/repo', id_factory=ids, now=_now
    )

    assert first == second
    count = ledger_connection.execute('SELECT COUNT(*) FROM PROJECT').fetchone()[0]
    assert count == 1


@pytest.mark.sqlite
def test_ingest_agent_session_event_creates_correct_fk_chain(ledger_connection, tmp_path):
    spool = tmp_path / 'events'
    _write_event(
        spool,
        '1.json',
        {
            'schema_version': 1,
            'kind': 'agent_session',
            'harness_session_id': 'harness-1',
            'cwd': '/repo',
            'agent_id': 'agent-1',
            'role': 'scout',
            'model': 'haiku',
            'total_tokens': 42,
            'duration_ms': 100,
        },
    )

    report = ingest_pending_events(
        ledger_connection, spool, id_factory=_id_factory(), now=_now
    )

    assert report.ingested == 1
    assert report.malformed == 0
    assert report.failed == 0
    assert list(spool.glob('*.json')) == []

    user_session = ledger_connection.execute(
        'SELECT user_session_id FROM USER_SESSION WHERE harness_session_id = ?',
        ('harness-1',),
    ).fetchone()
    assert user_session is not None
    run = ledger_connection.execute(
        'SELECT id, project_id, user_session_id FROM RUN'
    ).fetchone()
    assert run[2] == user_session[0]
    agent_session = ledger_connection.execute(
        'SELECT run_id, role, model, entrypoint_id FROM AGENT_SESSION'
    ).fetchone()
    assert agent_session == (run[0], 'scout', 'haiku', None)
    model_call = ledger_connection.execute(
        'SELECT input_tokens, output_tokens, duration_ms, provider_usage_json '
        'FROM MODEL_CALL'
    ).fetchone()
    assert model_call[0] is None
    assert model_call[1] is None
    assert model_call[2] == 100
    assert json.loads(model_call[3]) == {'total_tokens': 42}


@pytest.mark.sqlite
def test_ingest_agent_session_event_absent_usage_is_null_not_zero(
    ledger_connection, tmp_path
):
    spool = tmp_path / 'events'
    _write_event(
        spool,
        '1.json',
        {
            'schema_version': 1,
            'kind': 'agent_session',
            'harness_session_id': 'harness-1',
            'cwd': '/repo',
            'agent_id': 'agent-1',
            'role': 'scout',
            'model': 'haiku',
            'total_tokens': None,
            'duration_ms': None,
        },
    )

    ingest_pending_events(ledger_connection, spool, id_factory=_id_factory(), now=_now)

    model_call = ledger_connection.execute(
        'SELECT input_tokens, output_tokens, billed_tokens, duration_ms, '
        'provider_usage_json FROM MODEL_CALL'
    ).fetchone()
    assert model_call == (None, None, None, None, None)


@pytest.mark.sqlite
def test_ingest_two_agent_session_events_same_harness_session_one_user_session(
    ledger_connection, tmp_path
):
    spool = tmp_path / 'events'
    for index, agent_id in enumerate(('agent-1', 'agent-2')):
        _write_event(
            spool,
            f'{index}.json',
            {
                'schema_version': 1,
                'kind': 'agent_session',
                'harness_session_id': 'harness-1',
                'cwd': '/repo',
                'agent_id': agent_id,
                'role': 'scout',
                'model': 'haiku',
                'total_tokens': 10,
                'duration_ms': 5,
            },
        )

    report = ingest_pending_events(
        ledger_connection, spool, id_factory=_id_factory(), now=_now
    )

    assert report.ingested == 2
    user_sessions = ledger_connection.execute(
        'SELECT COUNT(*) FROM USER_SESSION WHERE harness_session_id = ?', ('harness-1',)
    ).fetchone()[0]
    assert user_sessions == 1
    agent_sessions = ledger_connection.execute(
        'SELECT COUNT(*) FROM AGENT_SESSION'
    ).fetchone()[0]
    assert agent_sessions == 2


@pytest.mark.sqlite
def test_ingest_replaying_the_same_agent_session_event_does_not_double_count_tokens(
    ledger_connection, tmp_path
):
    event = {
        'schema_version': 1,
        'kind': 'agent_session',
        'harness_session_id': 'harness-1',
        'cwd': '/repo',
        'agent_id': 'agent-1',
        'role': 'scout',
        'model': 'haiku',
        'total_tokens': 42,
        'duration_ms': 100,
    }
    spool = tmp_path / 'events'
    _write_event(spool, '1.json', event)
    ingest_pending_events(ledger_connection, spool, id_factory=_id_factory(), now=_now)

    # A second, independent batch replays the identical event (e.g. a retried
    # ingestion run) — must not create a second MODEL_CALL/AGENT_SESSION row.
    _write_event(spool, '2.json', event)
    ingest_pending_events(ledger_connection, spool, id_factory=_id_factory(), now=_now)

    assert ledger_connection.execute('SELECT COUNT(*) FROM MODEL_CALL').fetchone()[0] == 1
    assert (
        ledger_connection.execute('SELECT COUNT(*) FROM AGENT_SESSION').fetchone()[0] == 1
    )


@pytest.mark.sqlite
def test_ingest_compaction_event_links_artifact_and_agent_session(
    ledger_connection, tmp_path
):
    snapshot_dir = tmp_path / 'snapshot'
    snapshot_dir.mkdir()
    (snapshot_dir / 'telemetry.md').write_text('row')
    spool = tmp_path / 'events'
    _write_event(
        spool,
        '1.json',
        {
            'schema_version': 1,
            'kind': 'compaction',
            'harness_session_id': 'harness-1',
            'cwd': '/repo',
            'agent_type': 'main',
            'trigger': 'auto',
            'token_count': 9000,
            'snapshot_dir': str(snapshot_dir),
        },
    )

    report = ingest_pending_events(
        ledger_connection, spool, id_factory=_id_factory(), now=_now
    )

    assert report.ingested == 1
    compaction = ledger_connection.execute(
        'SELECT trigger, pre_tokens, snapshot_artifact_id, agent_session_id '
        'FROM COMPACTION_EVENT'
    ).fetchone()
    assert compaction[0] == 'auto'
    assert compaction[1] == 9000
    assert compaction[2] is not None
    artifact = ledger_connection.execute(
        'SELECT relative_path FROM ARTIFACT WHERE id = ?', (compaction[2],)
    ).fetchone()
    assert artifact[0] == str(snapshot_dir)
    agent_session = ledger_connection.execute(
        'SELECT id FROM AGENT_SESSION WHERE id = ?', (compaction[3],)
    ).fetchone()
    assert agent_session is not None


@pytest.mark.sqlite
def test_ingest_compaction_event_with_missing_snapshot_dir_leaves_artifact_null(
    ledger_connection, tmp_path
):
    spool = tmp_path / 'events'
    _write_event(
        spool,
        '1.json',
        {
            'schema_version': 1,
            'kind': 'compaction',
            'harness_session_id': 'harness-1',
            'cwd': '/repo',
            'agent_type': 'main',
            'trigger': 'auto',
            'token_count': None,
            'snapshot_dir': None,
        },
    )

    ingest_pending_events(ledger_connection, spool, id_factory=_id_factory(), now=_now)

    compaction = ledger_connection.execute(
        'SELECT pre_tokens, snapshot_artifact_id FROM COMPACTION_EVENT'
    ).fetchone()
    assert compaction == (None, None)


@pytest.mark.sqlite
def test_ingest_discards_malformed_and_unsupported_events(ledger_connection, tmp_path):
    spool = tmp_path / 'events'
    spool.mkdir()
    (spool / 'bad.json').write_text('not json', encoding='utf-8')
    _write_event(
        spool,
        'unsupported.json',
        {
            'schema_version': 1,
            'kind': 'no-such-kind',
            'harness_session_id': 'harness-1',
        },
    )

    report = ingest_pending_events(
        ledger_connection, spool, id_factory=_id_factory(), now=_now
    )

    assert report.malformed == 1
    assert report.unsupported == 1
    assert report.ingested == 0
    assert read_events(spool).events == ()
    assert read_events(spool).malformed == ()

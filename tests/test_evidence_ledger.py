"""Tests for artifact/evidence provenance schema and recording (SPEC.md §17.1, §17.2)."""

import sqlite3

import pytest

from ledger.artifact_store import ArtifactStore
from ledger.connection import connect
from ledger.evidence import CommandCapture, record_command_evidence
from ledger.migrations import SUPPORTED_SCHEMA_VERSION, migrate

_EVIDENCE_TABLES = ('ARTIFACT', 'EVIDENCE')
_EVIDENCE_INDEXES = (
    'idx_artifact_project_id',
    'idx_evidence_run_id',
    'idx_evidence_task_id',
    'idx_evidence_artifact_id',
)


@pytest.mark.sqlite
def test_fresh_init_reaches_the_evidence_schema_version(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')

    final_version = migrate(connection)

    assert final_version == SUPPORTED_SCHEMA_VERSION == 1
    connection.close()


@pytest.mark.sqlite
def test_fresh_init_creates_the_artifact_and_evidence_tables(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }

    for table in _EVIDENCE_TABLES:
        assert table in tables
    connection.close()


@pytest.mark.sqlite
def test_fresh_init_creates_every_evidence_index(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)

    indexes = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }

    for index in _EVIDENCE_INDEXES:
        assert index in indexes
    connection.close()


@pytest.mark.sqlite
def test_evidence_insert_fails_for_a_nonexistent_artifact(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_run(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO EVIDENCE (id, run_id, artifact_id, evidence_kind, created_at) '
            "VALUES ('evidence-1', 'run-1', 'no-such-artifact', 'command-result', "
            "'2026-07-20T00:00:00Z')"
        )
    connection.close()


@pytest.mark.sqlite
def test_compaction_event_snapshot_artifact_id_is_now_a_real_foreign_key(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_run(connection)
    _seed_agent_session(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO COMPACTION_EVENT '
            '(id, agent_session_id, trigger, snapshot_artifact_id, created_at) '
            "VALUES ('compaction-1', 'session-1', 'auto', 'no-such-artifact', "
            "'2026-07-20T00:00:00Z')"
        )
    connection.close()


@pytest.mark.sqlite
def test_record_command_evidence_stores_the_full_capture_on_failure(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_run(connection)
    store = ArtifactStore(tmp_path / 'artifacts')
    capture = _capture(exit_code=1, raw_output=b'AssertionError: boom\n' * 10)

    record = record_command_evidence(connection, store, capture)

    assert record.stored_full is True
    assert store.read(record.sha256) == capture.raw_output
    row = connection.execute(
        'SELECT run_id, artifact_id, criterion_id FROM EVIDENCE WHERE id = ?',
        (record.evidence_id,),
    ).fetchone()
    assert row == ('run-1', 'artifact-1', 'criterion-1')
    connection.close()


@pytest.mark.sqlite
def test_record_command_evidence_stores_only_a_preview_on_success(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_run(connection)
    store = ArtifactStore(tmp_path / 'artifacts')
    capture = _capture(exit_code=0, raw_output=b'.' * 20)

    record = record_command_evidence(connection, store, capture, preview_bytes=4)

    assert record.stored_full is False
    assert store.read(record.sha256) == b'....'
    connection.close()


@pytest.mark.sqlite
def test_record_command_evidence_never_persists_an_unredacted_secret(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_run(connection)
    artifact_root = tmp_path / 'artifacts'
    store = ArtifactStore(artifact_root)
    secret = b'sk-ant-api03-thisisafakesecretvalue1234567890'
    capture = _capture(exit_code=1, raw_output=b'Authorization: Bearer ' + secret)

    record_command_evidence(connection, store, capture)

    for artifact_file in artifact_root.rglob('*'):
        if artifact_file.is_file():
            assert secret not in artifact_file.read_bytes()
    connection.close()


def _capture(*, exit_code: int, raw_output: bytes) -> CommandCapture:
    return CommandCapture(
        evidence_id='evidence-1',
        artifact_id='artifact-1',
        project_id='project-1',
        run_id='run-1',
        task_id=None,
        criterion_id='criterion-1',
        evidence_kind='command-result',
        command='pytest',
        exit_code=exit_code,
        commit_sha='deadbeef',
        summary='pytest result',
        media_type='text/plain',
        retention_class='standard',
        raw_output=raw_output,
        created_at='2026-07-20T00:00:00Z',
    )


def _seed_run(connection: sqlite3.Connection) -> None:
    connection.execute(
        'INSERT INTO PROJECT (id, canonical_root, fingerprint, created_at, last_seen_at) '
        "VALUES ('project-1', '/repo', 'fp-1', "
        "'2026-07-20T00:00:00Z', '2026-07-20T00:00:00Z')"
    )
    connection.execute(
        'INSERT INTO USER_SESSION (user_session_id, harness_session_id, created_at) '
        "VALUES ('user-session-1', 'harness-1', '2026-07-20T00:00:00Z')"
    )
    connection.execute(
        'INSERT INTO RUN '
        '(id, project_id, user_session_id, delivery_mode, state, started_at) '
        "VALUES ('run-1', 'project-1', 'user-session-1', 'local', 'Planned', "
        "'2026-07-20T00:00:00Z')"
    )
    connection.commit()


def _seed_agent_session(connection: sqlite3.Connection) -> None:
    connection.execute(
        'INSERT INTO AGENT_SESSION '
        '(id, run_id, role, provider, model, state, started_at) '
        "VALUES ('session-1', 'run-1', 'implementer', 'claude', 'sonnet', "
        "'running', '2026-07-20T00:00:00Z')"
    )
    connection.commit()

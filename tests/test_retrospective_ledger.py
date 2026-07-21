"""Tests for the procedure/retrospective/evaluation schema (SPEC.md §17.2, §18)."""

import sqlite3

import pytest

from ledger.connection import connect
from ledger.migrations import SUPPORTED_SCHEMA_VERSION, migrate

_NEW_TABLES = (
    'RETROSPECTIVE',
    'RETRO_OBSERVATION',
    'PROCEDURE',
    'PROCEDURE_VERSION',
    'PROCEDURE_USE',
    'EVALUATION',
    'EVALUATION_METRIC',
)
_NEW_INDEXES = (
    'idx_retrospective_run_id',
    'idx_retro_observation_retrospective_id',
    'idx_procedure_project_id',
    'idx_procedure_version_procedure_id',
    'idx_procedure_version_artifact_id',
    'idx_procedure_use_procedure_version_id',
    'idx_procedure_use_task_id',
    'idx_procedure_use_agent_session_id',
    'idx_evaluation_memory_id',
    'idx_evaluation_procedure_version_id',
    'idx_evaluation_project_id',
    'idx_evaluation_evaluator_session_id',
    'idx_evaluation_metric_evaluation_id',
)
_CREATED_AT = '2026-07-20T00:00:00Z'


def _seed_project(
    connection: sqlite3.Connection, *, project_id: str = 'project-1'
) -> None:
    connection.execute(
        'INSERT INTO PROJECT (id, canonical_root, fingerprint, created_at, last_seen_at) '
        'VALUES (?, ?, ?, ?, ?)',
        (project_id, '/repo', f'fp-{project_id}', _CREATED_AT, _CREATED_AT),
    )
    connection.commit()


def _seed_run(connection: sqlite3.Connection, *, run_id: str = 'run-1') -> None:
    if (
        connection.execute("SELECT 1 FROM PROJECT WHERE id = 'project-1'").fetchone()
        is None
    ):
        _seed_project(connection)
    connection.execute(
        'INSERT INTO USER_SESSION (user_session_id, harness_session_id, created_at) '
        'VALUES (?, ?, ?)',
        ('user-session-1', 'harness-1', _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO RUN '
        '(id, project_id, user_session_id, delivery_mode, state, started_at) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (run_id, 'project-1', 'user-session-1', 'local', 'Planned', _CREATED_AT),
    )
    connection.commit()


def _seed_retrospective(
    connection: sqlite3.Connection,
    *,
    retrospective_id: str = 'retro-1',
    run_id: str = 'run-1',
) -> None:
    connection.execute(
        'INSERT INTO RETROSPECTIVE (id, run_id, status, created_at) VALUES (?, ?, ?, ?)',
        (retrospective_id, run_id, 'Pending', _CREATED_AT),
    )
    connection.commit()


def _seed_procedure(
    connection: sqlite3.Connection, *, procedure_id: str = 'procedure-1'
) -> None:
    if (
        connection.execute("SELECT 1 FROM PROJECT WHERE id = 'project-1'").fetchone()
        is None
    ):
        _seed_project(connection)
    connection.execute(
        'INSERT INTO PROCEDURE (id, project_id, name, scope, state, created_at) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (procedure_id, 'project-1', 'name', 'skill', 'active', _CREATED_AT),
    )
    connection.commit()


def _seed_memory(connection: sqlite3.Connection, *, memory_id: str = 'memory-1') -> None:
    if (
        connection.execute("SELECT 1 FROM PROJECT WHERE id = 'project-1'").fetchone()
        is None
    ):
        _seed_project(connection)
    connection.execute(
        'INSERT INTO MEMORY '
        '(id, origin_project_id, state, memory_kind, title, content, '
        'created_at, updated_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (
            memory_id,
            'project-1',
            'Candidate',
            'lesson',
            'title',
            'content',
            _CREATED_AT,
            _CREATED_AT,
        ),
    )
    connection.commit()


@pytest.mark.sqlite
def test_fresh_init_reaches_the_retrospective_schema_version(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')

    final_version = migrate(connection)

    assert final_version == SUPPORTED_SCHEMA_VERSION == 1
    connection.close()


@pytest.mark.sqlite
def test_fresh_init_creates_every_new_table(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }

    for table in _NEW_TABLES:
        assert table in tables
    connection.close()


@pytest.mark.sqlite
def test_fresh_init_creates_every_new_index(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)

    indexes = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }

    for index in _NEW_INDEXES:
        assert index in indexes
    connection.close()


@pytest.mark.sqlite
def test_retrospective_run_id_is_unique(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_run(connection)
    _seed_retrospective(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO RETROSPECTIVE (id, run_id, status, created_at) '
            "VALUES ('retro-2', 'run-1', 'Pending', ?)",
            (_CREATED_AT,),
        )
    connection.close()


@pytest.mark.sqlite
def test_retrospective_status_check_rejects_an_unrecognized_status(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_run(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO RETROSPECTIVE (id, run_id, status, created_at) '
            "VALUES ('retro-1', 'run-1', 'Bogus', ?)",
            (_CREATED_AT,),
        )
    connection.close()


@pytest.mark.sqlite
def test_procedure_version_status_check_rejects_an_unrecognized_status(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_procedure(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO PROCEDURE_VERSION '
            '(id, procedure_id, version_no, content_hash, status, created_at) '
            "VALUES ('pv-1', 'procedure-1', 1, 'hash-1', 'bogus', ?)",
            (_CREATED_AT,),
        )
    connection.close()


@pytest.mark.sqlite
def test_procedure_version_rejects_a_duplicate_version_number(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_procedure(connection)
    connection.execute(
        'INSERT INTO PROCEDURE_VERSION '
        '(id, procedure_id, version_no, content_hash, status, created_at) '
        "VALUES ('pv-1', 'procedure-1', 1, 'hash-1', 'active', ?)",
        (_CREATED_AT,),
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO PROCEDURE_VERSION '
            '(id, procedure_id, version_no, content_hash, status, created_at) '
            "VALUES ('pv-2', 'procedure-1', 1, 'hash-2', 'inactive', ?)",
            (_CREATED_AT,),
        )
    connection.close()


@pytest.mark.sqlite
def test_evaluation_requires_a_memory_or_a_procedure_version(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_project(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO EVALUATION '
            '(id, project_id, evaluation_kind, decision, created_at) '
            "VALUES ('eval-1', 'project-1', 'worth', 'promote', ?)",
            (_CREATED_AT,),
        )
    connection.close()


@pytest.mark.sqlite
def test_evaluation_accepts_a_memory_only_evaluation(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_memory(connection)

    connection.execute(
        'INSERT INTO EVALUATION '
        '(id, memory_id, project_id, evaluation_kind, decision, created_at) '
        "VALUES ('eval-1', 'memory-1', 'project-1', 'worth', 'promote', ?)",
        (_CREATED_AT,),
    )
    connection.commit()

    row = connection.execute(
        'SELECT id FROM EVALUATION WHERE id = ?', ('eval-1',)
    ).fetchone()
    assert row == ('eval-1',)
    connection.close()


@pytest.mark.sqlite
def test_memory_evidence_observation_id_is_now_a_real_foreign_key(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_run(connection)
    _seed_memory(connection)
    connection.execute(
        'INSERT INTO ARTIFACT '
        '(id, project_id, sha256, media_type, byte_size, relative_path, '
        'retention_class, redaction_state, created_at) '
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

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO MEMORY_EVIDENCE '
            '(memory_id, evidence_id, observation_id, relation, created_at) '
            "VALUES ('memory-1', 'evidence-1', 'no-such-observation', 'supports', ?)",
            (_CREATED_AT,),
        )
    connection.close()

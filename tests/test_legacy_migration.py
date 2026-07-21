"""Tests for `ledger.legacy_migration` (SPEC.md §19, §23 Microtask 17)."""

import itertools

import pytest

from ledger.legacy_migration import (
    LegacyImportRequest,
    discover_legacy_telemetry_files,
    import_legacy_workspace,
    import_telemetry_file,
)

_CREATED_AT = '2026-07-20T00:00:00Z'


def _now() -> str:
    return _CREATED_AT


def _id_factory():
    counter = itertools.count(1)

    def _next() -> str:
        return f'id-{next(counter)}'

    return _next


@pytest.fixture
def legacy_workspace(tmp_path):
    sessions = tmp_path / '.agentmaster' / 'sessions' / 'sess-1'
    sessions.mkdir(parents=True)
    (sessions / 'telemetry.md').write_text(
        'hook,scout,haiku,42,100\nexecute,implementer,sonnet,,50\n'
    )
    return tmp_path


def test_discover_legacy_telemetry_files_finds_session_scoped_file(legacy_workspace):
    found = discover_legacy_telemetry_files(legacy_workspace)

    assert len(found) == 1
    path, harness_session_id = found[0]
    assert (
        path == legacy_workspace / '.agentmaster' / 'sessions' / 'sess-1' / 'telemetry.md'
    )
    assert harness_session_id == 'sess-1'


def test_discover_legacy_telemetry_files_finds_root_file(tmp_path):
    am = tmp_path / '.agentmaster'
    am.mkdir()
    (am / 'telemetry.md').write_text('hook,scout,haiku,1,2\n')

    found = discover_legacy_telemetry_files(tmp_path)

    assert found == [(am / 'telemetry.md', 'legacy-root')]


def test_discover_legacy_telemetry_files_on_empty_workspace_is_empty(tmp_path):
    assert discover_legacy_telemetry_files(tmp_path) == []


@pytest.mark.sqlite
def test_dry_run_reports_without_writing(ledger_connection, legacy_workspace):
    path, harness_session_id = discover_legacy_telemetry_files(legacy_workspace)[0]

    report = import_telemetry_file(
        ledger_connection,
        path,
        LegacyImportRequest(
            harness_session_id=harness_session_id,
            project_id='unused',
            id_factory=_id_factory(),
            now=_now,
            apply=False,
        ),
    )

    assert report.imported == 2
    assert report.artifact_id is None
    assert ledger_connection.execute('SELECT COUNT(*) FROM RUN').fetchone()[0] == 0
    assert ledger_connection.execute('SELECT COUNT(*) FROM MODEL_CALL').fetchone()[0] == 0


@pytest.mark.sqlite
def test_import_legacy_workspace_dry_run_creates_no_project_row(
    ledger_connection, legacy_workspace
):
    import_legacy_workspace(
        ledger_connection,
        legacy_workspace,
        id_factory=_id_factory(),
        now=_now,
        apply=False,
    )

    assert ledger_connection.execute('SELECT COUNT(*) FROM PROJECT').fetchone()[0] == 0


@pytest.mark.sqlite
def test_apply_imports_rows_with_correct_fk_chain_and_null_not_fabricated(
    ledger_connection, legacy_workspace
):
    reports = import_legacy_workspace(
        ledger_connection,
        legacy_workspace,
        id_factory=_id_factory(),
        now=_now,
        apply=True,
    )

    assert len(reports) == 1
    report = reports[0]
    assert report.imported == 2
    assert report.artifact_id is not None

    project_count = ledger_connection.execute('SELECT COUNT(*) FROM PROJECT').fetchone()[
        0
    ]
    assert project_count == 1
    run = ledger_connection.execute(
        'SELECT project_id, user_session_id, state FROM RUN'
    ).fetchone()
    assert run[2] == 'Complete'
    agent_session = ledger_connection.execute(
        'SELECT run_id FROM AGENT_SESSION'
    ).fetchone()
    assert agent_session[0] is not None
    calls = ledger_connection.execute(
        'SELECT billed_tokens, duration_ms FROM MODEL_CALL ORDER BY duration_ms'
    ).fetchall()
    assert calls == [(None, 50), (42, 100)]

    artifact = ledger_connection.execute(
        'SELECT relative_path, project_id FROM ARTIFACT WHERE id = ?',
        (report.artifact_id,),
    ).fetchone()
    assert artifact[0] == str(
        legacy_workspace / '.agentmaster' / 'sessions' / 'sess-1' / 'telemetry.md'
    )
    assert artifact[1] == run[0]


@pytest.mark.sqlite
def test_running_import_twice_does_not_duplicate_rows(
    ledger_connection, legacy_workspace
):
    import_legacy_workspace(
        ledger_connection,
        legacy_workspace,
        id_factory=_id_factory(),
        now=_now,
        apply=True,
    )
    import_legacy_workspace(
        ledger_connection,
        legacy_workspace,
        id_factory=_id_factory(),
        now=_now,
        apply=True,
    )

    assert ledger_connection.execute('SELECT COUNT(*) FROM PROJECT').fetchone()[0] == 1
    assert ledger_connection.execute('SELECT COUNT(*) FROM RUN').fetchone()[0] == 1
    assert (
        ledger_connection.execute('SELECT COUNT(*) FROM AGENT_SESSION').fetchone()[0] == 1
    )
    assert ledger_connection.execute('SELECT COUNT(*) FROM MODEL_CALL').fetchone()[0] == 2
    assert ledger_connection.execute('SELECT COUNT(*) FROM ARTIFACT').fetchone()[0] == 1


@pytest.mark.sqlite
def test_original_file_is_preserved(ledger_connection, legacy_workspace):
    path, harness_session_id = discover_legacy_telemetry_files(legacy_workspace)[0]
    original = path.read_text()

    import_telemetry_file(
        ledger_connection,
        path,
        LegacyImportRequest(
            harness_session_id=harness_session_id,
            project_id='',
            id_factory=_id_factory(),
            now=_now,
            apply=False,
        ),
    )
    import_legacy_workspace(
        ledger_connection,
        legacy_workspace,
        id_factory=_id_factory(),
        now=_now,
        apply=True,
    )

    assert path.is_file()
    assert path.read_text() == original


@pytest.mark.sqlite
def test_malformed_row_is_reported_and_skipped(ledger_connection, tmp_path):
    am = tmp_path / '.agentmaster'
    am.mkdir()
    (am / 'telemetry.md').write_text('hook,scout,haiku,42,100\nnot,enough,fields\n')

    report = import_telemetry_file(
        ledger_connection,
        am / 'telemetry.md',
        LegacyImportRequest(
            harness_session_id='legacy-root',
            project_id='',
            id_factory=_id_factory(),
            now=_now,
            apply=False,
        ),
    )

    assert report.imported == 1
    assert report.malformed == 1


@pytest.mark.sqlite
def test_ambiguous_token_field_is_reported_and_not_fabricated(
    ledger_connection, tmp_path
):
    am = tmp_path / '.agentmaster'
    am.mkdir()
    (am / 'telemetry.md').write_text('hook,scout,haiku,not-a-number,100\n')

    reports = import_legacy_workspace(
        ledger_connection, tmp_path, id_factory=_id_factory(), now=_now, apply=True
    )

    assert reports[0].ambiguous == 1
    row = ledger_connection.execute('SELECT billed_tokens FROM MODEL_CALL').fetchone()
    assert row[0] is None

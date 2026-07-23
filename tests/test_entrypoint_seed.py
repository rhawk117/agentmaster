import itertools
import json

import pytest

from agentmaster.cli import main
from agentmaster.registry import CommandEntry
from ledger.connection import connect
from ledger.entrypoint_seed import seed_entrypoints

_CREATED_AT = '2026-07-20T00:00:00Z'

_COMMANDS = (CommandEntry(group='ledger', name='init', description='Create the ledger.'),)


def _now() -> str:
    return _CREATED_AT


def _id_factory():
    counter = itertools.count(1)

    def _next() -> str:
        return f'entrypoint-{next(counter)}'

    return _next


def _all_rows(connection):
    return connection.execute(
        'SELECT id, kind, name, source_path, active, created_at '
        'FROM ENTRYPOINT ORDER BY kind, name'
    ).fetchall()


@pytest.mark.sqlite
def test_seed_entrypoints_inserts_skill_agent_hook_and_command_rows(
    ledger_connection, make_manifest
):
    manifest = make_manifest(
        claude_skills=('agentmaster-plan',),
        workers=('scout',),
        claude_only_agents=('explore',),
        claude_hooks=('telemetry.py',),
        copilot_hooks=('copilot_telemetry_pre.py',),
    )

    report = seed_entrypoints(
        ledger_connection,
        id_factory=_id_factory(),
        now=_now,
        manifest=manifest,
        command_registry=_COMMANDS,
    )

    assert report.inserted == 6
    assert report.updated == 0
    assert report.deactivated == 0
    rows = _all_rows(ledger_connection)
    assert (
        'agent',
        'explore',
        'agents/explore.md',
        1,
        _CREATED_AT,
    ) in [row[1:] for row in rows]
    assert (
        'agent',
        'scout',
        'agents/scout.md',
        1,
        _CREATED_AT,
    ) in [row[1:] for row in rows]
    assert (
        'skill',
        'agentmaster-plan',
        'skills/agentmaster-plan/SKILL.md',
        1,
        _CREATED_AT,
    ) in [row[1:] for row in rows]
    assert ('hook', 'telemetry.py', 'hooks/telemetry.py', 1, _CREATED_AT) in [
        row[1:] for row in rows
    ]
    assert (
        'hook',
        'copilot_telemetry_pre.py',
        'hooks/copilot_telemetry_pre.py',
        1,
        _CREATED_AT,
    ) in [row[1:] for row in rows]
    assert ('command', 'ledger init', 'agentmaster/registry.py', 1, _CREATED_AT) in [
        row[1:] for row in rows
    ]


@pytest.mark.sqlite
def test_reseeding_unchanged_inputs_is_a_byte_for_byte_no_op(
    ledger_connection, make_manifest
):
    manifest = make_manifest(claude_skills=('agentmaster-plan',), workers=('scout',))

    seed_entrypoints(
        ledger_connection,
        id_factory=_id_factory(),
        now=_now,
        manifest=manifest,
        command_registry=_COMMANDS,
    )
    before = _all_rows(ledger_connection)

    second_report = seed_entrypoints(
        ledger_connection,
        id_factory=_id_factory(),
        now=_now,
        manifest=manifest,
        command_registry=_COMMANDS,
    )
    after = _all_rows(ledger_connection)

    assert second_report.inserted == 0
    assert second_report.updated == 0
    assert second_report.deactivated == 0
    assert before == after


@pytest.mark.sqlite
def test_reseeding_updates_a_row_whose_source_path_drifted(
    ledger_connection, make_manifest
):
    manifest = make_manifest(workers=('scout',))
    seed_entrypoints(
        ledger_connection,
        id_factory=_id_factory(),
        now=_now,
        manifest=manifest,
        command_registry=(),
    )
    ledger_connection.execute(
        "UPDATE ENTRYPOINT SET source_path = 'stale/path.md' "
        "WHERE kind = 'agent' AND name = 'scout'"
    )
    ledger_connection.commit()

    report = seed_entrypoints(
        ledger_connection,
        id_factory=_id_factory(),
        now=_now,
        manifest=manifest,
        command_registry=(),
    )

    assert report.updated == 1
    row = ledger_connection.execute(
        'SELECT source_path, active FROM ENTRYPOINT '
        "WHERE kind = 'agent' AND name = 'scout'"
    ).fetchone()
    assert row == ('agents/scout.md', 1)


@pytest.mark.sqlite
def test_reseeding_deactivates_a_row_whose_source_vanished(
    ledger_connection, make_manifest
):
    full_manifest = make_manifest(workers=('scout', 'implementer'))
    seed_entrypoints(
        ledger_connection,
        id_factory=_id_factory(),
        now=_now,
        manifest=full_manifest,
        command_registry=(),
    )

    shrunk_manifest = make_manifest(workers=('scout',))
    report = seed_entrypoints(
        ledger_connection,
        id_factory=_id_factory(),
        now=_now,
        manifest=shrunk_manifest,
        command_registry=(),
    )

    assert report.deactivated == 1
    row = ledger_connection.execute(
        "SELECT active FROM ENTRYPOINT WHERE kind = 'agent' AND name = 'implementer'"
    ).fetchone()
    assert row == (0,)
    count = ledger_connection.execute('SELECT COUNT(*) FROM ENTRYPOINT').fetchone()[0]
    assert count == 2


@pytest.mark.sqlite
def test_reseeding_reactivates_a_row_whose_source_returned(
    ledger_connection, make_manifest
):
    full_manifest = make_manifest(workers=('scout', 'implementer'))
    shrunk_manifest = make_manifest(workers=('scout',))
    seed_entrypoints(
        ledger_connection,
        id_factory=_id_factory(),
        now=_now,
        manifest=full_manifest,
        command_registry=(),
    )
    seed_entrypoints(
        ledger_connection,
        id_factory=_id_factory(),
        now=_now,
        manifest=shrunk_manifest,
        command_registry=(),
    )

    report = seed_entrypoints(
        ledger_connection,
        id_factory=_id_factory(),
        now=_now,
        manifest=full_manifest,
        command_registry=(),
    )

    assert report.updated == 1
    row = ledger_connection.execute(
        "SELECT active FROM ENTRYPOINT WHERE kind = 'agent' AND name = 'implementer'"
    ).fetchone()
    assert row == (1,)


@pytest.mark.sqlite
def test_entrypoint_name_lookup_within_a_kind_uses_the_index(
    ledger_connection, make_manifest
):
    seed_entrypoints(
        ledger_connection,
        id_factory=_id_factory(),
        now=_now,
        manifest=make_manifest(workers=('scout',)),
        command_registry=(),
    )

    plan = ledger_connection.execute(
        "EXPLAIN QUERY PLAN SELECT id FROM ENTRYPOINT WHERE kind = 'agent' AND name = ?",
        ('scout',),
    ).fetchall()

    detail = ' '.join(str(row[-1]) for row in plan)
    assert 'idx_entrypoint_kind_name' in detail


@pytest.mark.sqlite
def test_query_entrypoints_cli_returns_seeded_rows(capsys, tmp_path, make_manifest):
    ledger_path = tmp_path / 'ledger.sqlite3'
    assert main(['ledger', 'init', '--path', str(ledger_path)]) == 0
    connection = connect(ledger_path)
    seed_entrypoints(
        connection,
        id_factory=_id_factory(),
        now=_now,
        manifest=make_manifest(workers=('scout',)),
        command_registry=_COMMANDS,
    )
    connection.close()

    exit_code = main([
        'ledger',
        'query',
        'entrypoints',
        '--path',
        str(ledger_path),
        '--json',
    ])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 2
    assert {row['kind'] for row in payload} == {'agent', 'command'}

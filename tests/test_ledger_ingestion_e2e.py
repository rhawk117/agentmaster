"""Automatic, bounded spool-to-ledger ingestion (SPEC.md §16.3, §17, §23 M17).

Scenarios 2-4 of the ledger runtime plan. Red against v2.0.0 for structural
reasons documented per test -- missing auto-drain, not a crash: hooks spool
events to disk correctly today (`hooklib.spool_event`), but nothing invokes
`ledger.ingestion.ingest_pending_events` automatically at any checkpoint
(evidence 12), and `hooks/copilot_telemetry_post.py` never spools at all
(evidence 10).
"""

import json
import sqlite3

import pytest

from ledger.connection import connect as connect_ledger
from ledger.migrations import migrate as migrate_ledger

pytestmark = pytest.mark.subprocess


def _subagent_stop_payload(workspace, *, agent_id='agent-42'):
    return {
        'cwd': str(workspace),
        'session_id': 'sess-claude-1',
        'hook_event_name': 'SubagentStop',
        'agent_type': 'implementer',
        'agent_id': agent_id,
        'agent_model': 'claude-sonnet-5',
        'total_tokens': 1200,
    }


def test_subagent_stop_spools_but_never_auto_drains_into_ledger(tmp_path, run_hook):
    """Scenario 2: a realistic SubagentStop payload is spooled to disk (real,
    passing behavior), but v2.0.0 has no automatic drain at this checkpoint,
    so it never becomes an AGENT_SESSION/MODEL_CALL row without a manual
    `agentmaster ledger ingest-events` call.
    """
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    ledger_path = tmp_path / 'ledger.sqlite3'
    connection = connect_ledger(ledger_path)
    migrate_ledger(connection)
    connection.close()

    result = run_hook('telemetry', _subagent_stop_payload(workspace))
    assert result.returncode == 0, result.stderr

    spooled = list((workspace / '.agentmaster' / 'events').glob('*.json'))
    assert len(spooled) == 1, (
        f'expected the hook to spool exactly one event, found {spooled}'
    )
    event = json.loads(spooled[0].read_text(encoding='utf-8'))
    assert event['kind'] == 'agent_session'
    assert event['role'] == 'implementer'

    connection = sqlite3.connect(str(ledger_path))
    try:
        agent_session_rows = connection.execute(
            'SELECT COUNT(*) FROM AGENT_SESSION'
        ).fetchone()[0]
    finally:
        connection.close()

    assert agent_session_rows > 0, (
        'the SubagentStop event was spooled to disk but never ingested into '
        'AGENT_SESSION -- v2.0.0 has no automatic drain-at-checkpoint (only '
        '`agentmaster ledger ingest-events` drains, and nothing invokes it); '
        'this goes green once T3 wires a bounded auto-drain at the '
        'telemetry checkpoint'
    )


def test_retry_after_ledger_unavailable_persists_exactly_once_at_next_checkpoint(
    tmp_path, run_hook
):
    """Scenario 3: while the ledger is locked/busy, the hook must still exit 0
    and retain the spool (already true today via `hooklib.spool_event`'s
    fail-open write). Red part: once the ledger becomes available again, the
    *next checkpoint* must drain and clear the retained spool exactly once --
    no auto-drain exists pre-T3, so nothing ever clears it.
    """
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    ledger_path = tmp_path / 'ledger.sqlite3'
    connection = connect_ledger(ledger_path)
    migrate_ledger(connection)
    connection.close()

    locker = sqlite3.connect(str(ledger_path))
    locker.execute('BEGIN EXCLUSIVE')
    try:
        result = run_hook('telemetry', _subagent_stop_payload(workspace))
        assert result.returncode == 0, result.stderr

        spooled = list((workspace / '.agentmaster' / 'events').glob('*.json'))
        assert len(spooled) == 1, (
            'spool must retain the event while the ledger is unavailable'
        )
    finally:
        locker.rollback()
        locker.close()

    # "Next checkpoint": a later hook fires once the ledger is available again.
    result = run_hook('telemetry', _subagent_stop_payload(workspace, agent_id='agent-43'))
    assert result.returncode == 0, result.stderr

    remaining = list((workspace / '.agentmaster' / 'events').glob('*.json'))
    assert remaining == [], (
        'once the ledger is available again, the next checkpoint must drain '
        'and clear the retained spool -- no auto-drain exists pre-T3, so the '
        f'event retained during the lock is still sitting in the spool: {remaining}'
    )

    connection = sqlite3.connect(str(ledger_path))
    try:
        agent_session_rows = connection.execute(
            'SELECT COUNT(*) FROM AGENT_SESSION'
        ).fetchone()[0]
    finally:
        connection.close()
    assert agent_session_rows == 1, (
        'exactly one logical event should have been persisted once ingestion '
        f'ran, found {agent_session_rows}'
    )


def test_copilot_post_agent_spools_agent_session_like_claude(tmp_path, run_hook):
    """Scenario 4: Copilot parity. `copilot_telemetry_post.py` calls
    `append_telemetry` but never `hooklib.spool_event` (evidence 10), so zero
    Copilot `agent_session` events ever reach the spool, let alone the ledger.
    """
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    starts_dir = workspace / '.agentmaster' / '.starts'
    starts_dir.mkdir(parents=True)
    (starts_dir / 'copilot-queue').write_text(
        '1700000000.0 implementer\n', encoding='utf-8'
    )

    payload = {
        'cwd': str(workspace),
        'session_id': 'sess-copilot-1',
        'toolName': 'agent',
    }
    result = run_hook('copilot_telemetry_post', payload)
    assert result.returncode == 0, result.stderr

    telemetry_md = (
        workspace / '.agentmaster' / 'sessions' / 'sess-copilot-1' / 'telemetry.md'
    )
    assert telemetry_md.is_file(), 'existing telemetry.md append behavior regressed'

    spooled = list((workspace / '.agentmaster' / 'events').glob('*.json'))
    assert len(spooled) == 1, (
        'copilot_telemetry_post.py must spool a normalized `agent_session` '
        'event just like the Claude telemetry hook, but it currently never '
        f'calls hooklib.spool_event at all (found {len(spooled)} spooled files)'
    )
    event = json.loads(spooled[0].read_text(encoding='utf-8'))
    assert event['kind'] == 'agent_session'
    # Missing token/model must stay NULL, never a fabricated 0 (SPEC.md §16.3).
    assert event.get('total_tokens') is None
    assert event.get('model') in (None, '')

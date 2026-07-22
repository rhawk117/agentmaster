"""Automatic, bounded spool-to-ledger ingestion (SPEC.md §16.3, §17, §23 M17).

Scenarios 2-4 of the ledger runtime plan. Scenarios 2 and 3 exercise the
auto-drain through an INSTALLED hook (the auto-drain resolves the runtime
descriptor relative to the hook's own installed `__file__`, never guessing a
ledger path -- see `hooklib.load_runtime_descriptor`), so each installs into
a temp `CLAUDE_CONFIG_DIR`/agentmaster-home first and then invokes
`<claude_home>/agentmaster/hooks/telemetry.py` directly, exactly as the spec
phrase "through the installed telemetry hook" requires. Scenario 4 stays a
plain source-checkout hook invocation: it only asserts spooling, not ledger
ingestion, so it does not need an installed runtime.
"""

import json
import sqlite3

import pytest

from ledger.connection import connect as connect_ledger
from ledger.event_spool import SpooledEvent
from ledger.ingestion import (
    _read_run_id_marker,
    _resolve_run_preferring_marker,
    _RunResolutionContext,
    resolve_project,
    upsert_user_session,
)
from ledger.migrations import migrate as migrate_ledger


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


def _install_claude(run_cli, repo_root, tmp_path):
    """Install the Claude target into a disposable home, ledger enabled."""
    claude_home = tmp_path / 'claude-home'
    agentmaster_home = tmp_path / 'agentmaster-home'
    result = run_cli(
        [
            'install',
            '--target',
            'claude',
            '--no-input',
            '--agentmaster-home',
            str(agentmaster_home),
        ],
        cwd=repo_root,
        env_extra={'CLAUDE_CONFIG_DIR': str(claude_home)},
    )
    assert result.returncode == 0, result.stderr
    return claude_home, agentmaster_home


@pytest.mark.subprocess
@pytest.mark.integration
def test_subagent_stop_spools_but_never_auto_drains_into_ledger(
    tmp_path, run_cli, repo_root, installed_hook
):
    """Scenario 2: a realistic SubagentStop payload is spooled to disk (real,
    passing behavior), but v2.0.0 has no automatic drain at this checkpoint,
    so it never becomes an AGENT_SESSION/MODEL_CALL row without a manual
    `agentmaster ledger ingest-events` call. Run through the INSTALLED
    telemetry hook so the auto-drain can resolve the runtime descriptor
    (beside the installed hook) rather than needing a guessed ledger path.
    """
    claude_home, agentmaster_home = _install_claude(run_cli, repo_root, tmp_path)
    ledger_path = agentmaster_home / 'ledger.sqlite3'
    hook_path = claude_home / 'agentmaster' / 'hooks' / 'telemetry.py'

    workspace = tmp_path / 'workspace'
    workspace.mkdir()

    result = installed_hook(hook_path, _subagent_stop_payload(workspace), cwd=workspace)
    assert result.returncode == 0, result.stderr

    # The installed hook auto-drains synchronously, so by the time the
    # process exits the spool is already empty -- checked directly rather
    # than inspecting a transient spool file (no pending .agentmaster/events/
    # files after healthy ingestion, per the plan's end-to-end verification).
    remaining = list((workspace / '.agentmaster' / 'events').glob('*.json'))
    assert remaining == [], (
        f'expected the auto-drain to clear the spool, found {remaining}'
    )

    connection = sqlite3.connect(str(ledger_path))
    try:
        agent_session_rows = connection.execute(
            "SELECT COUNT(*) FROM AGENT_SESSION WHERE role = 'implementer'"
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


@pytest.mark.subprocess
@pytest.mark.integration
def test_retry_after_ledger_unavailable_persists_exactly_once_at_next_checkpoint(
    tmp_path, run_cli, repo_root, installed_hook
):
    """Scenario 3: while the ledger is locked/busy, the hook must still exit 0
    and retain the spool (already true today via `hooklib.spool_event`'s
    fail-open write). Red part: once the ledger becomes available again, the
    *next checkpoint* must drain and clear the retained spool exactly once --
    no auto-drain exists pre-T3, so nothing ever clears it. Run through the
    INSTALLED telemetry hook, same reasoning as scenario 2.
    """
    claude_home, agentmaster_home = _install_claude(run_cli, repo_root, tmp_path)
    ledger_path = agentmaster_home / 'ledger.sqlite3'
    hook_path = claude_home / 'agentmaster' / 'hooks' / 'telemetry.py'

    workspace = tmp_path / 'workspace'
    workspace.mkdir()

    locker = sqlite3.connect(str(ledger_path))
    locker.execute('BEGIN EXCLUSIVE')
    try:
        result = installed_hook(
            hook_path, _subagent_stop_payload(workspace), cwd=workspace
        )
        assert result.returncode == 0, result.stderr

        spooled = list((workspace / '.agentmaster' / 'events').glob('*.json'))
        assert len(spooled) == 1, (
            'spool must retain the event while the ledger is unavailable'
        )
    finally:
        locker.rollback()
        locker.close()

    # "Next checkpoint": the harness redelivers the same SubagentStop event
    # (same agent_id) once the ledger is available again -- this is what
    # "persists exactly once" tests: idempotent ingestion of a retried
    # delivery, via AGENT_SESSION's id being deterministic per (run, agent).
    result = installed_hook(
        hook_path,
        _subagent_stop_payload(workspace),
        cwd=workspace,
    )
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


@pytest.mark.subprocess
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


def test_read_run_id_marker_sanitizes_a_path_traversal_session_id(tmp_path):
    """A session id read from spooled JSON is untrusted input: a crafted
    `../`-style value must not let `_read_run_id_marker` escape the
    `sessions/` directory to read an arbitrary file elsewhere on disk.
    """
    agentmaster_dir = tmp_path / '.agentmaster'
    spool_dir = agentmaster_dir / 'events'
    spool_dir.mkdir(parents=True)

    secret = tmp_path / 'secret.run_id'
    secret.write_text('escaped-run-id', encoding='utf-8')

    malicious_session_id = '../../../secret'

    # The sanitized marker path (this session id collapses to a single
    # segment) has no marker written -- so nothing is read back, proving
    # the raw traversal path was never followed.
    assert _read_run_id_marker(spool_dir, malicious_session_id) is None

    sanitized_dir = agentmaster_dir / 'sessions' / '.._.._.._secret'
    sanitized_dir.mkdir(parents=True)
    (sanitized_dir / '.run_id').write_text('sanitized-run-id', encoding='utf-8')

    assert _read_run_id_marker(spool_dir, malicious_session_id) == 'sanitized-run-id'


def test_resolve_run_preferring_marker_ignores_a_marker_naming_an_ended_run(tmp_path):
    """A stale `.run_id` marker pointing at an already-ENDED RUN must not
    reattach new AGENT_SESSION/MODEL_CALL rows to that finished run -- a
    fresh open RUN must be used instead.
    """
    ledger_path = tmp_path / 'ledger.sqlite3'
    connection = connect_ledger(ledger_path)
    migrate_ledger(connection)

    now = lambda: '2026-07-21T00:00:00Z'  # noqa: E731
    counter = iter(f'id-{n}' for n in range(100))
    id_factory = lambda: next(counter)  # noqa: E731

    project_id = resolve_project(
        connection, canonical_root=str(tmp_path), id_factory=id_factory, now=now
    )
    user_session_id = upsert_user_session(
        connection, 'sess-1', id_factory=id_factory, now=now
    )
    ended_run_id = id_factory()
    connection.execute(
        'INSERT INTO RUN '
        '(id, project_id, user_session_id, delivery_mode, state, started_at, ended_at) '
        "VALUES (?, ?, ?, 'local', 'Complete', ?, ?)",
        (ended_run_id, project_id, user_session_id, now(), now()),
    )
    connection.commit()

    workspace = tmp_path / 'workspace'
    spool_dir = workspace / '.agentmaster' / 'events'
    spool_dir.mkdir(parents=True)
    session_marker_dir = workspace / '.agentmaster' / 'sessions' / 'sess-1'
    session_marker_dir.mkdir(parents=True)
    (session_marker_dir / '.run_id').write_text(ended_run_id, encoding='utf-8')

    event = SpooledEvent(
        path=tmp_path / 'event.json',
        kind='agent_session',
        harness_session_id='sess-1',
        fields={},
    )

    resolved_run_id = _resolve_run_preferring_marker(
        connection,
        event,
        spool_dir,
        _RunResolutionContext(
            project_id=project_id,
            user_session_id=user_session_id,
            id_factory=id_factory,
            now=now,
        ),
    )
    connection.close()

    assert resolved_run_id != ended_run_id

"""Tests for the agentmaster lifecycle hook scripts."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_HOOKS = Path(__file__).resolve().parent.parent / 'hooks'


def _run(name, payload, tmp_path, env=None, raw=None):
    hook = _HOOKS / f'{name}.py'
    stdin = raw if raw is not None else json.dumps(payload)
    return subprocess.run(  # noqa: S603
        [sys.executable, str(hook)],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        check=False,
    )


def test_telemetry_writes_line_and_consumes_start(tmp_path):
    starts = tmp_path / '.agentmaster' / '.starts'
    starts.mkdir(parents=True)
    (starts / 'abc').write_text(str(time.time() - 1))
    payload = {
        'cwd': str(tmp_path),
        'agent_type': 'scout',
        'agent_id': 'abc',
        'total_tokens': 42,
    }
    result = _run('telemetry', payload, tmp_path)
    assert result.returncode == 0
    line = (tmp_path / '.agentmaster' / 'telemetry.md').read_text()
    assert line.startswith('hook,scout,,42,')
    assert line.endswith('\n')
    assert not (starts / 'abc').exists()


def test_subagent_start_records_timestamp(tmp_path):
    payload = {'cwd': str(tmp_path), 'agent_id': 'xyz'}
    result = _run('subagent_start', payload, tmp_path)
    assert result.returncode == 0
    started = tmp_path / '.agentmaster' / '.starts' / 'xyz'
    assert started.is_file()
    assert float(started.read_text()) > 0


def test_precompact_snapshot_copies_and_logs(tmp_path):
    am = tmp_path / '.agentmaster'
    am.mkdir()
    (am / 'ledger.md').write_text('evidence')
    payload = {'cwd': str(tmp_path)}
    result = _run('precompact_snapshot', payload, tmp_path)
    assert result.returncode == 0
    snapshots = list((am / 'compaction-snapshots').iterdir())
    assert len(snapshots) == 1
    assert (snapshots[0] / 'ledger.md').read_text() == 'evidence'
    assert 'hook,precompact,,,\n' in (am / 'telemetry.md').read_text()


def test_session_context_emits_pointer(tmp_path):
    am = tmp_path / '.agentmaster'
    am.mkdir()
    (am / 'ledger.md').write_text('x')
    result = _run('session_context', {'cwd': str(tmp_path)}, tmp_path)
    assert result.returncode == 0
    assert 'ledger.md' in result.stdout
    assert '.agentmaster/' in result.stdout


def test_session_context_silent_without_artifacts(tmp_path):
    result = _run('session_context', {'cwd': str(tmp_path)}, tmp_path)
    assert result.returncode == 0
    assert result.stdout.strip() == ''


def test_git_guard_blocks_push_claude_shape(tmp_path):
    payload = {'cwd': str(tmp_path), 'tool_input': {'command': 'git push'}}
    result = _run('git_guard', payload, tmp_path)
    assert result.returncode == 2
    assert 'git push' in result.stderr
    assert result.stdout.strip() == ''


def test_git_guard_blocks_push_copilot_shape(tmp_path):
    payload = {
        'cwd': str(tmp_path),
        'toolName': 'execute',
        'toolArgs': {'command': 'git push origin main'},
    }
    result = _run('git_guard', payload, tmp_path)
    assert result.returncode == 2
    assert '"decision": "deny"' in result.stdout


def test_git_guard_allows_diff(tmp_path):
    payload = {'cwd': str(tmp_path), 'tool_input': {'command': 'git diff'}}
    result = _run('git_guard', payload, tmp_path)
    assert result.returncode == 0


def test_git_guard_ignores_non_shell_tool(tmp_path):
    payload = {
        'cwd': str(tmp_path),
        'toolName': 'read_file',
        'toolArgs': {'command': 'git push'},
    }
    result = _run('git_guard', payload, tmp_path)
    assert result.returncode == 0


def test_git_guard_off_switch(tmp_path):
    env = {**os.environ, 'AGENTMASTER_GIT_GUARD': 'off'}
    payload = {'cwd': str(tmp_path), 'tool_input': {'command': 'git push'}}
    result = _run('git_guard', payload, tmp_path, env=env)
    assert result.returncode == 0


def test_dispatch_guard_blocks_when_env_set(tmp_path):
    env = {**os.environ, 'CLAUDE_CODE_SUBAGENT_MODEL': 'haiku'}
    result = _run('dispatch_guard', {}, tmp_path, env=env)
    assert result.returncode == 2
    assert 'CLAUDE_CODE_SUBAGENT_MODEL' in result.stderr


def test_dispatch_guard_allows_when_unset(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != 'CLAUDE_CODE_SUBAGENT_MODEL'}
    result = _run('dispatch_guard', {}, tmp_path, env=env)
    assert result.returncode == 0


def test_malformed_json_exits_zero_everywhere(tmp_path):
    hooks = (
        'telemetry',
        'subagent_start',
        'precompact_snapshot',
        'session_context',
        'git_guard',
        'dispatch_guard',
        'copilot_telemetry_pre',
        'copilot_telemetry_post',
    )
    for name in hooks:
        result = _run(name, None, tmp_path, raw='not json')
        assert result.returncode == 0, (name, result.stderr)


def test_copilot_pre_queues_agent(tmp_path):
    payload = {'cwd': str(tmp_path), 'toolName': 'agent', 'toolArgs': {'agent': 'scout'}}
    result = _run('copilot_telemetry_pre', payload, tmp_path)
    assert result.returncode == 0
    queue = tmp_path / '.agentmaster' / '.starts' / 'copilot-queue'
    ts, agent = queue.read_text().strip().split(' ', 1)
    assert agent == 'scout'
    assert float(ts) > 0


def test_copilot_pre_ignores_other_tools(tmp_path):
    payload = {'cwd': str(tmp_path), 'toolName': 'execute', 'toolArgs': {'command': 'x'}}
    result = _run('copilot_telemetry_pre', payload, tmp_path)
    assert result.returncode == 0
    assert not (tmp_path / '.agentmaster' / '.starts' / 'copilot-queue').exists()


def test_copilot_post_pops_fifo(tmp_path):
    starts = tmp_path / '.agentmaster' / '.starts'
    starts.mkdir(parents=True)
    (starts / 'copilot-queue').write_text(
        f'{time.time() - 1} scout\n{time.time()} planner\n'
    )
    payload = {'cwd': str(tmp_path), 'toolName': 'agent', 'toolArgs': {}}
    result = _run('copilot_telemetry_post', payload, tmp_path)
    assert result.returncode == 0
    line = (tmp_path / '.agentmaster' / 'telemetry.md').read_text()
    assert line.startswith('hook,scout,,,')
    assert line.endswith('\n')
    remaining = (starts / 'copilot-queue').read_text()
    assert 'planner' in remaining
    assert 'scout' not in remaining


def test_copilot_post_empty_queue(tmp_path):
    payload = {'cwd': str(tmp_path), 'toolName': 'agent', 'toolArgs': {}}
    result = _run('copilot_telemetry_post', payload, tmp_path)
    assert result.returncode == 0
    line = (tmp_path / '.agentmaster' / 'telemetry.md').read_text()
    assert line == 'hook,agent,,,\n'


_TELEMETRY_REPORT = (
    Path(__file__).resolve().parent.parent / 'scripts' / 'telemetry_report.py'
)


def _run_report(cwd, *args):
    return subprocess.run(  # noqa: S603
        [sys.executable, str(_TELEMETRY_REPORT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_telemetry_report_summarizes_per_agent(tmp_path):
    am = tmp_path / '.agentmaster'
    am.mkdir()
    (am / 'telemetry.md').write_text(
        'hook,scout,,120,3000\n'
        'hook,scout,,80,1000\n'
        'hook,implementer,,,\n'
        'not a telemetry line\n'
    )

    result = _run_report(tmp_path)

    assert result.returncode == 0, result.stderr
    assert 'scout' in result.stdout
    assert '200' in result.stdout
    assert 'implementer' in result.stdout


def test_telemetry_report_missing_file_exits_one(tmp_path):
    result = _run_report(tmp_path)

    assert result.returncode == 1
    assert 'telemetry' in result.stderr.lower()

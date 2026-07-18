"""Tests for the agentmaster lifecycle hook scripts."""

import json
import os
import time

import pytest

pytestmark = pytest.mark.subprocess


def test_telemetry_writes_line_and_consumes_start(tmp_path, run_hook):
    starts = tmp_path / '.agentmaster' / '.starts'
    starts.mkdir(parents=True)
    (starts / 'abc').write_text(str(time.time() - 1))
    payload = {
        'cwd': str(tmp_path),
        'agent_type': 'scout',
        'agent_id': 'abc',
        'total_tokens': 42,
    }
    result = run_hook('telemetry', payload)
    assert result.returncode == 0
    line = (tmp_path / '.agentmaster' / 'telemetry.md').read_text()
    assert line.startswith('hook,scout,,42,')
    assert line.endswith('\n')
    assert not (starts / 'abc').exists()


def test_telemetry_row_carries_phase_and_model(tmp_path, run_hook):
    am = tmp_path / '.agentmaster'
    (am / '.starts').mkdir(parents=True)
    (am / '.phase').write_text('execute\n')
    (am / '.starts' / 'abc').write_text(str(time.time() - 1))
    session = tmp_path / 'session'
    (session / 'subagents').mkdir(parents=True)
    entry = {
        'message': {
            'model': 'claude-haiku-4-5',
            'usage': {'input_tokens': 10, 'output_tokens': 5},
        }
    }
    (session / 'subagents' / 'agent-abc.jsonl').write_text(json.dumps(entry) + '\n')
    payload = {
        'cwd': str(tmp_path),
        'agent_type': 'scout',
        'agent_id': 'abc',
        'transcript_path': str(session / 'main.jsonl'),
    }
    result = run_hook('telemetry', payload)
    assert result.returncode == 0
    line = (am / 'telemetry.md').read_text()
    assert line.startswith('execute,scout,claude-haiku-4-5,15,')


def test_subagent_start_records_timestamp(tmp_path, run_hook):
    payload = {'cwd': str(tmp_path), 'agent_id': 'xyz'}
    result = run_hook('subagent_start', payload)
    assert result.returncode == 0
    started = tmp_path / '.agentmaster' / '.starts' / 'xyz'
    assert started.is_file()
    assert float(started.read_text()) > 0


def test_precompact_snapshot_copies_and_logs(tmp_path, run_hook):
    am = tmp_path / '.agentmaster'
    am.mkdir()
    (am / 'ledger.md').write_text('evidence')
    payload = {'cwd': str(tmp_path)}
    result = run_hook('precompact_snapshot', payload)
    assert result.returncode == 0
    snapshots = list((am / 'compaction-snapshots').iterdir())
    assert len(snapshots) == 1
    assert (snapshots[0] / 'ledger.md').read_text() == 'evidence'
    assert 'hook,precompact,,,\n' in (am / 'telemetry.md').read_text()


def test_session_context_emits_pointer(tmp_path, run_hook):
    am = tmp_path / '.agentmaster'
    am.mkdir()
    (am / 'ledger.md').write_text('x')
    result = run_hook('session_context', {'cwd': str(tmp_path)})
    assert result.returncode == 0
    assert 'ledger.md' in result.stdout
    assert '.agentmaster/' in result.stdout


def test_session_context_silent_without_artifacts(tmp_path, run_hook):
    result = run_hook('session_context', {'cwd': str(tmp_path)})
    assert result.returncode == 0
    assert result.stdout.strip() == ''


def _arm_phase(tmp_path, phase='plan'):
    am = tmp_path / '.agentmaster'
    am.mkdir(exist_ok=True)
    (am / '.phase').write_text(f'{phase}\n')
    return am


def test_cost_boundary_blocks_repo_write_during_phase(tmp_path, run_hook):
    _arm_phase(tmp_path)
    payload = {
        'cwd': str(tmp_path),
        'tool_name': 'Write',
        'tool_input': {'file_path': str(tmp_path / 'src' / 'main.py')},
    }
    result = run_hook('cost_boundary', payload)
    assert result.returncode == 2
    assert 'plan phase' in result.stderr


def test_cost_boundary_blocks_bash_during_phase(tmp_path, run_hook):
    _arm_phase(tmp_path, 'review')
    payload = {
        'cwd': str(tmp_path),
        'tool_name': 'Bash',
        'tool_input': {'command': 'pytest'},
    }
    result = run_hook('cost_boundary', payload)
    assert result.returncode == 2


def test_cost_boundary_allows_write_outside_workspace(tmp_path, run_hook):
    _arm_phase(tmp_path)
    plan_file = tmp_path.parent / 'claude-plans' / 'plan.md'
    payload = {
        'cwd': str(tmp_path),
        'tool_name': 'Write',
        'tool_input': {'file_path': str(plan_file)},
    }
    result = run_hook('cost_boundary', payload)
    assert result.returncode == 0


def test_cost_boundary_allows_agentmaster_write(tmp_path, run_hook):
    am = _arm_phase(tmp_path)
    payload = {
        'cwd': str(tmp_path),
        'tool_name': 'Write',
        'tool_input': {'file_path': str(am / '.phase')},
    }
    result = run_hook('cost_boundary', payload)
    assert result.returncode == 0


def test_cost_boundary_noop_without_marker(tmp_path, run_hook):
    payload = {
        'cwd': str(tmp_path),
        'tool_name': 'Bash',
        'tool_input': {'command': 'pytest'},
    }
    result = run_hook('cost_boundary', payload)
    assert result.returncode == 0


def test_dispatch_guard_blocks_when_env_set(run_hook):
    env = {**os.environ, 'CLAUDE_CODE_SUBAGENT_MODEL': 'haiku'}
    result = run_hook('dispatch_guard', {}, env=env)
    assert result.returncode == 2
    assert 'CLAUDE_CODE_SUBAGENT_MODEL' in result.stderr


def test_dispatch_guard_allows_when_unset(run_hook):
    env = {k: v for k, v in os.environ.items() if k != 'CLAUDE_CODE_SUBAGENT_MODEL'}
    result = run_hook('dispatch_guard', {}, env=env)
    assert result.returncode == 0


def test_malformed_json_exits_zero_everywhere(run_hook):
    hooks = (
        'telemetry',
        'subagent_start',
        'precompact_snapshot',
        'session_context',
        'cost_boundary',
        'dispatch_guard',
        'copilot_telemetry_pre',
        'copilot_telemetry_post',
    )
    for name in hooks:
        result = run_hook(name, None, raw='not json')
        assert result.returncode == 0, (name, result.stderr)


def test_copilot_pre_queues_agent(tmp_path, run_hook):
    payload = {'cwd': str(tmp_path), 'toolName': 'agent', 'toolArgs': {'agent': 'scout'}}
    result = run_hook('copilot_telemetry_pre', payload)
    assert result.returncode == 0
    queue = tmp_path / '.agentmaster' / '.starts' / 'copilot-queue'
    ts, agent = queue.read_text().strip().split(' ', 1)
    assert agent == 'scout'
    assert float(ts) > 0


def test_copilot_pre_ignores_other_tools(tmp_path, run_hook):
    payload = {'cwd': str(tmp_path), 'toolName': 'execute', 'toolArgs': {'command': 'x'}}
    result = run_hook('copilot_telemetry_pre', payload)
    assert result.returncode == 0
    assert not (tmp_path / '.agentmaster' / '.starts' / 'copilot-queue').exists()


def test_copilot_post_pops_fifo(tmp_path, run_hook):
    starts = tmp_path / '.agentmaster' / '.starts'
    starts.mkdir(parents=True)
    (starts / 'copilot-queue').write_text(
        f'{time.time() - 1} scout\n{time.time()} planner\n'
    )
    payload = {'cwd': str(tmp_path), 'toolName': 'agent', 'toolArgs': {}}
    result = run_hook('copilot_telemetry_post', payload)
    assert result.returncode == 0
    line = (tmp_path / '.agentmaster' / 'telemetry.md').read_text()
    assert line.startswith('hook,scout,,,')
    assert line.endswith('\n')
    remaining = (starts / 'copilot-queue').read_text()
    assert 'planner' in remaining
    assert 'scout' not in remaining


def test_copilot_post_empty_queue(tmp_path, run_hook):
    payload = {'cwd': str(tmp_path), 'toolName': 'agent', 'toolArgs': {}}
    result = run_hook('copilot_telemetry_post', payload)
    assert result.returncode == 0
    line = (tmp_path / '.agentmaster' / 'telemetry.md').read_text()
    assert line == 'hook,agent,,,\n'

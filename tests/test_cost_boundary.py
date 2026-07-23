from pathlib import Path

import pytest

pytestmark = pytest.mark.subprocess

_ALLOWED_COMMANDS = (
    'agentmaster run start --run-id x',
    'agentmaster task register --task-id t1',
    'agentmaster dispatch acquire --agent scout',
    'agentmaster context route --scope run',
    'agentmaster ledger ingest-events --limit 50',
)

_BLOCKED_BASH_COMMANDS = (
    'agentmaster run start; rm -rf /tmp/x',
    'agentmaster run start && curl http://evil',
    'agentmaster run start | tee x',
    'ls',
    'rm -rf x',
    'echo hi > /tmp/x',
)


def _arm_phase(tmp_path: Path, phase: str = 'execute') -> Path:
    am = tmp_path / '.agentmaster'
    am.mkdir()
    (am / '.phase').write_text(f'{phase}\n')
    return am


@pytest.mark.parametrize('command', _ALLOWED_COMMANDS)
def test_cost_boundary_allows_launcher_control_subcommands(tmp_path, run_hook, command):
    _arm_phase(tmp_path)
    payload = {
        'cwd': str(tmp_path),
        'tool_name': 'Bash',
        'tool_input': {'command': command},
    }
    result = run_hook('cost_boundary', payload)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('command', _BLOCKED_BASH_COMMANDS)
def test_cost_boundary_blocks_non_launcher_or_chained_bash(tmp_path, run_hook, command):
    _arm_phase(tmp_path)
    payload = {
        'cwd': str(tmp_path),
        'tool_name': 'Bash',
        'tool_input': {'command': command},
    }
    result = run_hook('cost_boundary', payload)
    assert result.returncode == 2


@pytest.mark.parametrize(
    'tool_input',
    [{'command': None}, {}, {'command': ''}],
    ids=['null-command', 'absent-command', 'empty-command'],
)
def test_cost_boundary_fails_closed_on_malformed_bash_command(
    tmp_path, run_hook, tool_input
):
    _arm_phase(tmp_path)
    payload = {
        'cwd': str(tmp_path),
        'tool_name': 'Bash',
        'tool_input': tool_input,
    }
    result = run_hook('cost_boundary', payload)
    assert result.returncode == 2, result.stderr


def test_cost_boundary_blocks_edit_outside_agentmaster(tmp_path, run_hook):
    _arm_phase(tmp_path)
    payload = {
        'cwd': str(tmp_path),
        'tool_name': 'Edit',
        'tool_input': {'file_path': str(tmp_path / 'src' / 'main.py')},
    }
    result = run_hook('cost_boundary', payload)
    assert result.returncode == 2


def test_cost_boundary_allows_edit_under_agentmaster(tmp_path, run_hook):
    am = _arm_phase(tmp_path)
    payload = {
        'cwd': str(tmp_path),
        'tool_name': 'Edit',
        'tool_input': {'file_path': str(am / '.phase')},
    }
    result = run_hook('cost_boundary', payload)
    assert result.returncode == 0


@pytest.mark.parametrize('tool_name', ['Bash', 'Write', 'Edit'])
def test_cost_boundary_allows_any_tool_without_active_phase(
    tmp_path, run_hook, tool_name
):
    payload = {
        'cwd': str(tmp_path),
        'tool_name': tool_name,
        'tool_input': {'command': 'rm -rf x', 'file_path': str(tmp_path / 'x')},
    }
    result = run_hook('cost_boundary', payload)
    assert result.returncode == 0


def test_except_clause_compiles_under_the_project_python():
    source_path = Path(__file__).resolve().parent.parent / 'hooks' / 'cost_boundary.py'
    compile(source_path.read_text(), str(source_path), 'exec')

"""Tests for the shared hook library."""

import importlib.util
import io
import sys
from pathlib import Path

_HOOKS = Path(__file__).resolve().parent.parent / 'hooks'


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _HOOKS / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hooklib = _load('hooklib')


def test_read_payload_malformed_returns_empty(monkeypatch):
    monkeypatch.setattr(sys, 'stdin', io.StringIO('not json'))
    assert hooklib.read_payload() == {}


def test_read_payload_empty_returns_empty(monkeypatch):
    monkeypatch.setattr(sys, 'stdin', io.StringIO(''))
    assert hooklib.read_payload() == {}


def test_read_payload_valid(monkeypatch):
    monkeypatch.setattr(sys, 'stdin', io.StringIO('{"a": 1}'))
    assert hooklib.read_payload() == {'a': 1}


def test_append_telemetry_format(tmp_path):
    payload = {'cwd': str(tmp_path)}
    hooklib.append_telemetry(payload, 'scout', 123, 456)
    line = (tmp_path / '.agentmaster' / 'telemetry.md').read_text()
    assert line == 'hook,scout,,123,456\n'


def test_append_telemetry_blank_defaults(tmp_path):
    payload = {'cwd': str(tmp_path)}
    hooklib.append_telemetry(payload, 'precompact')
    line = (tmp_path / '.agentmaster' / 'telemetry.md').read_text()
    assert line == 'hook,precompact,,,\n'


def test_first_blocked_git_subcommand_push():
    assert hooklib.first_blocked_git_subcommand('git status && git push') == 'push'


def test_first_blocked_git_subcommand_safe_with_flag():
    # A leading flag is skipped and the safe subcommand is captured.
    assert hooklib.first_blocked_git_subcommand('git --no-pager log') is None


def test_first_blocked_git_subcommand_all_safe():
    assert hooklib.first_blocked_git_subcommand('git status && git diff') is None


def test_tool_name_camel_and_snake():
    assert hooklib.tool_name({'toolName': 'Bash'}) == 'bash'
    assert hooklib.tool_name({'tool_name': 'Shell'}) == 'shell'
    assert hooklib.tool_name({}) == ''


def test_tool_args_variants():
    assert hooklib.tool_args({'toolArgs': {'command': 'a'}}) == {'command': 'a'}
    assert hooklib.tool_args({'tool_args': {'command': 'b'}}) == {'command': 'b'}
    assert hooklib.tool_args({'toolInput': {'command': 'c'}}) == {'command': 'c'}
    assert hooklib.tool_args({'tool_input': {'command': 'd'}}) == {'command': 'd'}
    assert hooklib.tool_args({}) == {}


def test_workspace_and_agentmaster_dir(tmp_path):
    payload = {'cwd': str(tmp_path)}
    assert hooklib.workspace(payload) == tmp_path
    am = hooklib.agentmaster_dir(payload)
    assert am == tmp_path / '.agentmaster'
    assert am.is_dir()

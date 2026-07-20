"""Tests for the shared hook library."""

import importlib.util
import io
import sys
from pathlib import Path

_HOOKS = Path(__file__).resolve().parent.parent / 'hooks'


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _HOOKS / f'{name}.py')
    assert spec is not None
    assert spec.loader is not None
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


def test_append_telemetry_stamps_active_phase(tmp_path):
    payload = {'cwd': str(tmp_path)}
    am = tmp_path / '.agentmaster'
    am.mkdir()
    (am / '.phase').write_text('review\n')
    hooklib.append_telemetry(payload, 'scout', 1, 2, 'sonnet')
    line = (am / 'telemetry.md').read_text()
    assert line == 'review,scout,sonnet,1,2\n'


def test_current_phase_reads_strips_and_degrades(tmp_path):
    am = tmp_path / '.agentmaster'
    am.mkdir()
    (am / '.phase').write_text('plan\n')
    assert hooklib.current_phase(am) == 'plan'
    (am / '.phase').write_text('')
    assert hooklib.current_phase(am) == ''
    assert hooklib.current_phase(tmp_path / 'missing') == ''


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


def test_read_payload_non_dict_json_returns_empty(monkeypatch):
    for raw in ('[1, 2]', '"scout"', '42', 'null'):
        monkeypatch.setattr(sys, 'stdin', io.StringIO(raw))
        assert hooklib.read_payload() == {}


def test_compaction_context_defaults_when_payload_bare():
    ctx = hooklib.compaction_context({})
    assert ctx.agent_type == 'main'
    assert ctx.trigger == ''
    assert ctx.threshold_percent == ''
    assert ctx.pre_tokens == ''
    assert ctx.post_tokens == ''
    assert ctx.session_id == ''


def test_compaction_context_distinguishes_implementer():
    ctx = hooklib.compaction_context({'agent_type': 'implementer'})
    assert ctx.agent_type == 'implementer'


def test_compaction_context_distinguishes_other_subagent():
    ctx = hooklib.compaction_context({'agent_name': 'scout'})
    assert ctx.agent_type == 'scout'


def test_compaction_context_extracts_trigger_and_threshold():
    ctx = hooklib.compaction_context({'trigger': 'auto', 'threshold_percent': 50})
    assert ctx.trigger == 'auto'
    assert ctx.threshold_percent == '50'


def test_compaction_context_extracts_threshold_alt_key():
    ctx = hooklib.compaction_context({'auto_compact_percent': 75})
    assert ctx.threshold_percent == '75'


def test_compaction_context_extracts_tokens():
    ctx = hooklib.compaction_context({'pre_tokens': 9000, 'post_tokens': 500})
    assert ctx.pre_tokens == '9000'
    assert ctx.post_tokens == '500'


def test_compaction_context_extracts_tokens_alt_keys():
    ctx = hooklib.compaction_context({'tokens_before': 111, 'tokens_after': 22})
    assert ctx.pre_tokens == '111'
    assert ctx.post_tokens == '22'


def test_compaction_context_extracts_session_identifier():
    ctx = hooklib.compaction_context({'session_id': 'sess-1'})
    assert ctx.session_id == 'sess-1'


def test_compaction_context_falls_back_to_agent_id_for_session():
    ctx = hooklib.compaction_context({'agent_id': 'agent-9'})
    assert ctx.session_id == 'agent-9'


def test_compaction_context_fails_open_on_malformed_values():
    class Boom:
        def __bool__(self):
            raise RuntimeError('boom')

    ctx = hooklib.compaction_context({'agent_type': Boom()})
    assert ctx.agent_type == 'main'

"""Tests for the versioned owned-state store (SPEC.md §14)."""

import pytest

from installer.managed_state import OwnedState, OwnedStateError, parse, render


def test_parse_missing_text_is_empty_state():
    assert parse(None) == OwnedState()
    assert parse('') == OwnedState()
    assert parse('   ') == OwnedState()


def test_with_value_and_get_round_trip():
    state = OwnedState().with_value('claude', 'hooks.PreToolUse', ['x'])

    assert state.get('claude', 'hooks.PreToolUse') == ['x']
    assert state.get('claude', 'missing') is None
    assert state.get('claude', 'missing', 'default') == 'default'


def test_with_value_does_not_mutate_original():
    original = OwnedState()
    updated = original.with_value('claude', 'k', 'v')

    assert original.get('claude', 'k') is None
    assert updated.get('claude', 'k') == 'v'


def test_render_then_parse_round_trips():
    state = (
        OwnedState()
        .with_value('claude', 'hooks.PreToolUse', ['x'])
        .with_value('claude', 'env.PCT', '50')
    )

    parsed = parse(render(state))

    assert parsed == state


def test_parse_rejects_non_object_document():
    with pytest.raises(OwnedStateError):
        parse('[]')


def test_parse_rejects_invalid_json():
    with pytest.raises(OwnedStateError, match='invalid JSON'):
        parse('not json')


def test_parse_rejects_unsupported_schema_version():
    with pytest.raises(OwnedStateError, match='schema_version'):
        parse('{"schema_version": 99, "targets": {}}')


def test_parse_rejects_non_object_targets():
    with pytest.raises(OwnedStateError, match='targets'):
        parse('{"schema_version": 1, "targets": []}')

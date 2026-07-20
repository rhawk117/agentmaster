"""Tests for the Claude settings.json parse/validate/merge/strip logic."""

import pytest

from installer.claude_settings import (
    ClaudeSettingsError,
    is_ours,
    merge_hook_events,
    strip_hook_events,
    validate_settings,
)

MARKER = 'agentmaster/hooks'


def _entry(command: str) -> dict:
    return {'hooks': [{'type': 'command', 'command': command}]}


def test_validate_settings_accepts_well_formed_document():
    document = {
        'hooks': {'PreToolUse': [_entry(f'python3 "{MARKER}/x.py"')]},
        'env': {'SOME_VAR': 'value'},
        'other': True,
    }

    assert validate_settings(document) == document


def test_validate_settings_rejects_non_object_root():
    with pytest.raises(ClaudeSettingsError, match=r'\$'):
        validate_settings([])


def test_validate_settings_rejects_non_object_hooks():
    with pytest.raises(ClaudeSettingsError, match='hooks'):
        validate_settings({'hooks': []})


def test_validate_settings_rejects_non_array_event():
    with pytest.raises(ClaudeSettingsError, match=r'hooks\.PreToolUse'):
        validate_settings({'hooks': {'PreToolUse': {}}})


def test_validate_settings_rejects_malformed_hook_entry():
    with pytest.raises(ClaudeSettingsError, match=r'hooks\.PreToolUse\[0\]'):
        validate_settings({'hooks': {'PreToolUse': ['not-an-object']}})


def test_validate_settings_rejects_non_command_hook_type():
    entry = {'hooks': [{'type': 'script', 'command': 'x'}]}
    with pytest.raises(ClaudeSettingsError, match='type'):
        validate_settings({'hooks': {'PreToolUse': [entry]}})


def test_validate_settings_rejects_non_string_hook_command():
    entry = {'hooks': [{'type': 'command', 'command': 123}]}
    with pytest.raises(ClaudeSettingsError, match='command'):
        validate_settings({'hooks': {'PreToolUse': [entry]}})


def test_validate_settings_rejects_non_object_env():
    with pytest.raises(ClaudeSettingsError, match='env'):
        validate_settings({'env': []})


def test_validate_settings_rejects_non_string_env_value():
    with pytest.raises(ClaudeSettingsError, match=r'env\.PCT'):
        validate_settings({'env': {'PCT': 50}})


def test_is_ours_true_only_when_every_command_matches_marker():
    ours = _entry(f'python3 "{MARKER}/x.py"')
    assert is_ours(ours, MARKER)

    theirs = _entry('echo custom')
    assert not is_ours(theirs, MARKER)


def test_merge_hook_events_adds_entries_and_preserves_user_entries():
    user_entry = _entry('echo custom')
    settings = {'hooks': {'PreToolUse': [user_entry]}}
    new_entry = _entry(f'python3 "{MARKER}/dispatch_guard.py"')

    new_settings, owned = merge_hook_events(
        settings, {'PreToolUse': [new_entry]}, owned={}, marker=MARKER
    )

    assert new_settings['hooks']['PreToolUse'] == [user_entry, new_entry]
    assert owned == {'PreToolUse': [new_entry]}


def test_merge_hook_events_replaces_previously_owned_entry():
    old_entry = _entry(f'python3 "{MARKER}/old_path.py"')
    new_entry = _entry(f'python3 "{MARKER}/new_path.py"')
    settings = {'hooks': {'PreToolUse': [old_entry]}}

    new_settings, owned = merge_hook_events(
        settings,
        {'PreToolUse': [new_entry]},
        owned={'PreToolUse': [old_entry]},
        marker=MARKER,
    )

    assert new_settings['hooks']['PreToolUse'] == [new_entry]
    assert owned == {'PreToolUse': [new_entry]}


def test_merge_hook_events_replaces_legacy_marker_matched_entry_with_no_owned_record():
    legacy_entry = _entry(f'python3 "{MARKER}/dispatch_guard.py"')
    new_entry = _entry(f'python3 "{MARKER}/dispatch_guard.py" --v2')
    settings = {'hooks': {'PreToolUse': [legacy_entry]}}

    new_settings, _owned = merge_hook_events(
        settings, {'PreToolUse': [new_entry]}, owned={}, marker=MARKER
    )

    assert new_settings['hooks']['PreToolUse'] == [new_entry]


def test_strip_hook_events_removes_only_exact_owned_entries():
    owned_entry = _entry(f'python3 "{MARKER}/dispatch_guard.py"')
    user_entry = _entry('echo custom')
    settings = {'hooks': {'PreToolUse': [owned_entry, user_entry]}}

    stripped = strip_hook_events(settings, {'PreToolUse': [owned_entry]})

    assert stripped['hooks']['PreToolUse'] == [user_entry]


def test_strip_hook_events_preserves_user_edited_formerly_owned_entry():
    """The whole point of owned-state tracking: an edited entry survives uninstall."""
    owned_entry = _entry(f'python3 "{MARKER}/dispatch_guard.py"')
    edited_entry = _entry(f'python3 "{MARKER}/dispatch_guard.py" --custom-flag')
    settings = {'hooks': {'PreToolUse': [edited_entry]}}

    stripped = strip_hook_events(settings, {'PreToolUse': [owned_entry]})

    assert stripped['hooks']['PreToolUse'] == [edited_entry]

"""Parse, validate, and plan Claude `settings.json` mutations (SPEC.md §13/§14).

Deep, fail-closed shape validation for the mutable JSON surfaces Agentmaster
touches: the root object, `hooks`, each event's entry array, each hook
entry, and `env`. `merge_hook_events`/`strip_hook_events` are pure functions
over already-parsed documents — `installer.claude` owns the file I/O and
folds the result into the same transactional batch as agents and hooks.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


class ClaudeSettingsError(ValueError):
    """`settings.json` (or a value derived from it) has an invalid shape.

    Parameters
    ----------
    key_path
        Dotted/indexed JSON location (e.g. ``hooks.PreToolUse[0].command``).
    message
        Human-readable reason.
    """

    def __init__(self, key_path: str, message: str) -> None:
        self.key_path = key_path
        super().__init__(f'{key_path}: {message}')


def validate_settings(document: object) -> dict:
    """Fail-closed shape validation; returns `document` unchanged when valid.

    Raises
    ------
    ClaudeSettingsError
        `document` isn't a JSON object, `hooks`/`env` aren't objects, an
        event's entries aren't an array, or a hook entry is malformed.
    """
    if not isinstance(document, dict):
        raise ClaudeSettingsError('$', 'settings.json must contain a JSON object')
    hooks = document.get('hooks', {})
    if not isinstance(hooks, dict):
        raise ClaudeSettingsError('hooks', 'must be a JSON object')
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            raise ClaudeSettingsError(f'hooks.{event}', 'must be a JSON array')
        for index, entry in enumerate(entries):
            _validate_hook_entry(f'hooks.{event}[{index}]', entry)
    env = document.get('env', {})
    if not isinstance(env, dict):
        raise ClaudeSettingsError('env', 'must be a JSON object')
    for key, value in env.items():
        if not isinstance(value, str):
            raise ClaudeSettingsError(f'env.{key}', 'must be a string')
    return document


def _validate_hook_entry(key_path: str, entry: object) -> None:
    if not isinstance(entry, dict):
        raise ClaudeSettingsError(key_path, 'must be a JSON object')
    commands = entry.get('hooks')
    if not isinstance(commands, list):
        raise ClaudeSettingsError(f'{key_path}.hooks', 'must be a JSON array')
    for index, command in enumerate(commands):
        _validate_command_hook(f'{key_path}.hooks[{index}]', command)


def _validate_command_hook(key_path: str, command: object) -> None:
    if not isinstance(command, dict):
        raise ClaudeSettingsError(key_path, 'must be a JSON object')
    if command.get('type') != 'command':
        raise ClaudeSettingsError(f'{key_path}.type', "must be 'command'")
    if not isinstance(command.get('command'), str):
        raise ClaudeSettingsError(f'{key_path}.command', 'must be a string')


def is_ours(entry: dict, marker: str) -> bool:
    """True when every command hook in `entry` references our install-path marker.

    A content-based fallback for entries installed before owned-state
    tracking existed; `merge_hook_events` uses it alongside the precise
    `owned` record so an upgrade from an older install still converges to
    exactly the current managed set.
    """
    commands = entry.get('hooks', [])
    return bool(commands) and all(
        isinstance(hook, dict) and marker in hook.get('command', '') for hook in commands
    )


def _hooks_dict(settings: Mapping[str, object]) -> dict[str, list]:
    """Return `settings['hooks']`'s event arrays; callers assume pre-validated shape."""
    hooks = settings.get('hooks')
    if not isinstance(hooks, dict):
        return {}
    return {
        event: entries
        for event, entries in hooks.items()
        if isinstance(event, str) and isinstance(entries, list)
    }


def merge_hook_events(
    settings: Mapping[str, object],
    events: Mapping[str, list],
    *,
    owned: Mapping[str, list],
    marker: str,
) -> tuple[dict, dict[str, list]]:
    """Return `(new_settings, new_owned)` with this run's managed entries in place.

    Any entry recorded in `owned[event]` from a prior install, or matching
    the legacy content `marker`, is removed first; every other entry in the
    array — the user's own — is left untouched. `new_owned` records exactly
    what this call installed, for a later `strip_hook_events` to use.
    """
    hooks = _hooks_dict(settings)
    new_owned: dict[str, list] = {}
    for event, entries in events.items():
        previously_owned = owned.get(event, [])
        current = [
            entry
            for entry in hooks.get(event, [])
            if entry not in previously_owned and not is_ours(entry, marker)
        ]
        current.extend(entries)
        hooks[event] = current
        new_owned[event] = entries
    new_settings = dict(settings)
    new_settings['hooks'] = hooks
    return new_settings, new_owned


def strip_hook_events(settings: Mapping[str, object], owned: Mapping[str, list]) -> dict:
    """Remove only entries that still exactly equal what we last installed.

    An entry the user has since edited no longer matches and survives —
    this is the precise counterpart to `merge_hook_events`'s permissive
    pre-clear, and the fix for "later user edits survive uninstall".
    """
    hooks = _hooks_dict(settings)
    for event, owned_entries in owned.items():
        if event in hooks:
            hooks[event] = [entry for entry in hooks[event] if entry not in owned_entries]
    new_settings = dict(settings)
    new_settings['hooks'] = hooks
    return new_settings

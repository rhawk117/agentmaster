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

AUTO_COMPACT_ENV_KEY = 'CLAUDE_AUTOCOMPACT_PCT_OVERRIDE'


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


def _env_dict(settings: Mapping[str, object]) -> dict[str, str]:
    """Return `settings['env']`; callers assume pre-validated shape."""
    env = settings.get('env')
    if not isinstance(env, dict):
        return {}
    return {
        key: value
        for key, value in env.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def merge_auto_compact_override(
    settings: Mapping[str, object], *, owned: Mapping[str, object] | None, percent: int
) -> tuple[dict, dict[str, object]]:
    """Return `(new_settings, new_owned)` setting the auto-compact env override.

    The first time Agentmaster takes ownership of `AUTO_COMPACT_ENV_KEY`
    (`owned` is `None`), the current environment value is captured as
    `new_owned['original']` so a later `strip_auto_compact_override` can
    restore exactly the pre-Agentmaster value (SPEC.md §15). A later call
    with `owned` already set reuses its recorded `original` rather than
    re-capturing Agentmaster's own prior value.
    """
    env = _env_dict(settings)
    original = owned['original'] if owned is not None else env.get(AUTO_COMPACT_ENV_KEY)
    env[AUTO_COMPACT_ENV_KEY] = str(percent)
    new_settings = dict(settings)
    new_settings['env'] = env
    return new_settings, {'value': str(percent), 'original': original}


def strip_auto_compact_override(
    settings: Mapping[str, object], owned: Mapping[str, object] | None
) -> dict:
    """Restore the pre-Agentmaster env value only if it still matches what we set.

    Mirrors `strip_hook_events`: a user edit since install (the current env
    value no longer equals `owned['value']`) survives and is left alone.
    """
    if owned is None:
        return dict(settings)
    env = _env_dict(settings)
    if env.get(AUTO_COMPACT_ENV_KEY) != owned.get('value'):
        return dict(settings)
    original = owned.get('original')
    if isinstance(original, str):
        env[AUTO_COMPACT_ENV_KEY] = original
    else:
        env.pop(AUTO_COMPACT_ENV_KEY, None)
    new_settings = dict(settings)
    new_settings['env'] = env
    return new_settings

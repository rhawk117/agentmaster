from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

AUTO_COMPACT_ENV_KEY = 'CLAUDE_AUTOCOMPACT_PCT_OVERRIDE'


class ClaudeSettingsError(ValueError):
    def __init__(self, key_path: str, message: str) -> None:
        self.key_path = key_path
        super().__init__(f'{key_path}: {message}')


def validate_settings(document: object) -> dict:
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
    commands = entry.get('hooks', [])
    return bool(commands) and all(
        isinstance(hook, dict) and marker in hook.get('command', '') for hook in commands
    )


def _hooks_dict(settings: Mapping[str, object]) -> dict[str, list]:
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
    hooks = _hooks_dict(settings)
    for event, owned_entries in owned.items():
        if event in hooks:
            hooks[event] = [entry for entry in hooks[event] if entry not in owned_entries]
    new_settings = dict(settings)
    new_settings['hooks'] = hooks
    return new_settings


def _env_dict(settings: Mapping[str, object]) -> dict[str, str]:
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
    env = _env_dict(settings)
    original = owned['original'] if owned is not None else env.get(AUTO_COMPACT_ENV_KEY)
    env[AUTO_COMPACT_ENV_KEY] = str(percent)
    new_settings = dict(settings)
    new_settings['env'] = env
    return new_settings, {'value': str(percent), 'original': original}


def strip_auto_compact_override(
    settings: Mapping[str, object], owned: Mapping[str, object] | None
) -> dict:
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

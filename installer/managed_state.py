"""Versioned owned-state tracking for conditional restore (SPEC.md §14).

Records only what Agentmaster itself last installed for each managed key —
never a copy of unrelated user configuration — so a later install or
uninstall can act on exactly what Agentmaster owns, preserving anything the
user changed since. Pure parse/render; `installer.claude` owns the file I/O.
"""

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

SCHEMA_VERSION = 1


class OwnedStateError(ValueError):
    """The owned-state document is malformed or has an unsupported schema version."""


@dataclass(frozen=True, slots=True)
class OwnedState:
    """All Agentmaster-managed values, keyed by target then by managed key."""

    targets: dict[str, dict[str, object]] = field(default_factory=dict)

    def get(self, target: str, key: str, default: object = None) -> object:
        """Return the recorded value for `target`/`key`, or `default` if unset."""
        return self.targets.get(target, {}).get(key, default)

    def with_value(self, target: str, key: str, value: object) -> OwnedState:
        """Return a new `OwnedState` with `target`/`key` recorded as `value`."""
        targets = {name: dict(keys) for name, keys in self.targets.items()}
        targets.setdefault(target, {})[key] = value
        return OwnedState(targets=targets)


def parse(text: str | None) -> OwnedState:
    """Parse the owned-state JSON document; missing/empty text is empty state.

    Raises
    ------
    OwnedStateError
        `text` is present but not valid JSON, isn't an object, or its
        `schema_version` isn't the version this installer understands.
    """
    if not text or not text.strip():
        return OwnedState()
    try:
        document = json.loads(text)
    except ValueError as error:
        raise OwnedStateError(f'invalid JSON: {error}') from error
    if not isinstance(document, dict):
        raise OwnedStateError('owned-state document must be a JSON object')
    version = document.get('schema_version')
    if version != SCHEMA_VERSION:
        raise OwnedStateError(
            f'owned-state schema_version: expected {SCHEMA_VERSION}, got {version!r}'
        )
    targets = document.get('targets', {})
    if not isinstance(targets, dict):
        raise OwnedStateError('owned-state targets must be a JSON object')
    return OwnedState(targets=targets)


def render(state: OwnedState) -> str:
    """Serialize `state` deterministically (sorted keys) for a stable diff."""
    document: Mapping[str, object] = {
        'schema_version': SCHEMA_VERSION,
        'targets': state.targets,
    }
    return json.dumps(document, indent=2, sort_keys=True) + '\n'

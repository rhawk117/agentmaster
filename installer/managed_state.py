import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

SCHEMA_VERSION = 1


class OwnedStateError(ValueError): ...


@dataclass(frozen=True, slots=True)
class OwnedState:
    targets: dict[str, dict[str, object]] = field(default_factory=dict)

    def get(self, target: str, key: str, default: object = None) -> object:
        return self.targets.get(target, {}).get(key, default)

    def with_value(self, target: str, key: str, value: object) -> OwnedState:
        targets = {name: dict(keys) for name, keys in self.targets.items()}
        targets.setdefault(target, {})[key] = value
        return OwnedState(targets=targets)


def parse(text: str | None) -> OwnedState:
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
    document: Mapping[str, object] = {
        'schema_version': SCHEMA_VERSION,
        'targets': state.targets,
    }
    return json.dumps(document, indent=2, sort_keys=True) + '\n'

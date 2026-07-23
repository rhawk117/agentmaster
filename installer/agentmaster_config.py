import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

SCHEMA_VERSION = 1
_MANAGED_TABLES = (
    'paths',
    'orchestration',
    'agents.claude.orchestrator',
    'agents.claude.implementer',
    'agents.claude.reviewer',
    'ledger',
)


class AgentmasterConfigError(ValueError):
    def __init__(self, key_path: str, message: str) -> None:
        self.key_path = key_path
        super().__init__(f'{key_path}: {message}')


@dataclass(frozen=True, slots=True)
class AgentmasterConfigPlan:
    ledger_path: str
    artifact_path: str
    ledger_enabled: bool
    delivery_mode: str
    orchestrator_model: str
    orchestrator_effort: str
    implementer_model: str
    implementer_effort: str
    reviewer_model: str
    reviewer_effort: str
    raw_capture: str
    redaction: str


def validate_document(document: Mapping[str, object]) -> None:
    version = document.get('schema_version')
    if version != SCHEMA_VERSION:
        raise AgentmasterConfigError(
            'schema_version', f'expected {SCHEMA_VERSION}, got {version!r}'
        )
    for dotted in _MANAGED_TABLES:
        value = _get_dotted(document, dotted)
        if value is not _MISSING and not isinstance(value, dict):
            raise AgentmasterConfigError(dotted, 'must be a table')


_MISSING = object()


def _get_dotted(document: Mapping[str, object], dotted: str) -> object:
    node: object = document
    for part in dotted.split('.'):
        if not isinstance(node, dict):
            return node
        if part not in node:
            return _MISSING
        node = node.get(part)
    return node


def render_managed_block(plan: AgentmasterConfigPlan) -> str:
    return (
        f'schema_version = {SCHEMA_VERSION}\n\n'
        '[paths]\n'
        f'ledger = "{plan.ledger_path}"\n'
        f'artifacts = "{plan.artifact_path}"\n\n'
        '[orchestration]\n'
        f'delivery_mode = "{plan.delivery_mode}"\n\n'
        '[agents.claude.orchestrator]\n'
        f'model = "{plan.orchestrator_model}"\n'
        f'effort = "{plan.orchestrator_effort}"\n\n'
        '[agents.claude.implementer]\n'
        f'model = "{plan.implementer_model}"\n'
        f'effort = "{plan.implementer_effort}"\n\n'
        '[agents.claude.reviewer]\n'
        f'model = "{plan.reviewer_model}"\n'
        f'effort = "{plan.reviewer_effort}"\n\n'
        '[ledger]\n'
        f'enabled = {"true" if plan.ledger_enabled else "false"}\n'
        f'raw_output = "{plan.raw_capture}"\n'
        f'redaction = "{plan.redaction}"\n'
    )


def render_config(plan: AgentmasterConfigPlan, existing_text: str | None) -> str:
    managed = render_managed_block(plan)
    if not existing_text or not existing_text.strip():
        return managed

    try:
        document = tomllib.loads(existing_text)
    except tomllib.TOMLDecodeError as error:
        raise AgentmasterConfigError('$', f'invalid TOML: {error}') from error
    validate_document(document)

    managed_top_names = {name.split('.')[0] for name in _MANAGED_TABLES}
    unmanaged_names = set(document) - {'schema_version'} - managed_top_names
    if not unmanaged_names:
        return managed
    preserved = _extract_unmanaged_blocks(existing_text, unmanaged_names)
    return f'{managed}\n{preserved}'


def _extract_unmanaged_blocks(text: str, names: set[str]) -> str:
    blocks: list[str] = []
    capture = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith('['):
            header = stripped.strip('[]')
            capture = header.split('.')[0] in names
        if capture:
            blocks.append(line)
    return ''.join(blocks)

import re
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from os import PathLike

SCHEMA_VERSION = 1
MODEL_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
DEFAULT_AGENTMASTER_HOME = Path.home() / '.agentmaster'


class Target(StrEnum):
    CLAUDE = 'claude'
    COPILOT = 'copilot'
    ALL = 'all'

    def expand(self) -> tuple[Target, ...]:
        return (Target.CLAUDE, Target.COPILOT) if self is Target.ALL else (self,)


class Role(StrEnum):
    COORDINATOR = 'coordinator'
    ORCHESTRATOR = 'orchestrator'
    IMPLEMENTER = 'implementer'
    REVIEWER = 'reviewer'


class Effort(StrEnum):
    LOW = 'low'
    MEDIUM = 'medium'
    HIGH = 'high'
    XHIGH = 'xhigh'
    MAX = 'max'


DEFAULT_ROLE_MODEL: Mapping[tuple[Target, Role], str] = {
    (Target.CLAUDE, Role.COORDINATOR): 'opus',
    (Target.CLAUDE, Role.ORCHESTRATOR): 'sonnet',
    (Target.CLAUDE, Role.IMPLEMENTER): 'sonnet',
    (Target.CLAUDE, Role.REVIEWER): 'opus',
    (Target.COPILOT, Role.COORDINATOR): 'claude-opus-4.8',
    (Target.COPILOT, Role.IMPLEMENTER): 'claude-sonnet-4.6',
}
DEFAULT_ROLE_EFFORT: Mapping[Role, Effort] = {
    Role.ORCHESTRATOR: Effort.MEDIUM,
    Role.IMPLEMENTER: Effort.MEDIUM,
    Role.REVIEWER: Effort.HIGH,
}
ROLE_RATIONALE: Mapping[Role, str] = {
    Role.COORDINATOR: 'planning and architectural judgment',
    Role.ORCHESTRATOR: 'persistent control work, not final review',
    Role.IMPLEMENTER: 'plans contain hard decisions; worker executes',
    Role.REVIEWER: 'independent correctness and safety gate',
}


class DeliveryMode(StrEnum):
    LOCAL = 'local'
    COMMIT = 'commit'
    PULL_REQUEST = 'pull-request'
    MERGE = 'merge'


class RawCapture(StrEnum):
    FAILURES = 'failures'


class RedactionMode(StrEnum):
    STANDARD = 'standard'


class ConfigError(ValueError):
    def __init__(self, key_path: str, message: str) -> None:
        self.key_path = key_path
        super().__init__(f'{key_path}: {message}')


@dataclass(frozen=True, slots=True)
class RoleOverride:
    model: str
    effort: Effort | None = None

    def frontmatter_fields(self) -> dict[str, str]:
        fields = {'model': self.model}
        if self.effort is not None:
            fields['effort'] = self.effort.value
        return fields


@dataclass(frozen=True, slots=True)
class UnresolvedConfig:
    target: Target
    dry_run: bool = False
    no_input: bool = False
    claude_dir: Path | None = None
    copilot_dir: Path | None = None
    config_path: Path | None = None
    agentmaster_home: Path | None = None
    claude_model: str | None = None
    copilot_model: str | None = None
    claude_orchestrator_model: str | None = None
    claude_orchestrator_effort: Effort | None = None
    claude_implementer_model: str | None = None
    claude_implementer_effort: Effort | None = None
    claude_review_model: str | None = None
    claude_review_effort: Effort | None = None
    copilot_implementer_model: str | None = None
    ledger_path: Path | None = None
    no_ledger: bool = False
    artifact_dir: Path | None = None
    delivery_mode: DeliveryMode | None = None
    auto_compact_percent: int | None = None
    clear_auto_compact_override: bool = False


@dataclass(frozen=True, slots=True)
class ClaudeRoleConfig:
    coordinator_model: str
    orchestrator: RoleOverride
    implementer: RoleOverride
    reviewer: RoleOverride


@dataclass(frozen=True, slots=True)
class CopilotRoleConfig:
    coordinator_model: str
    implementer_model: str


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    targets: tuple[Target, ...]
    dry_run: bool
    no_input: bool
    claude_dir: Path | None
    copilot_dir: Path | None
    agentmaster_home: Path
    ledger_path: Path
    artifact_path: Path
    ledger_enabled: bool
    delivery_mode: DeliveryMode
    raw_capture: RawCapture
    redaction: RedactionMode

    def summary_lines(self) -> list[str]:
        ledger_display = str(self.ledger_path) if self.ledger_enabled else 'disabled'
        artifacts_display = str(self.artifact_path) if self.ledger_enabled else 'disabled'
        return [
            f'agentmaster home        {self.agentmaster_home}',
            f'ledger                  {ledger_display}',
            f'artifacts               {artifacts_display}',
            f'delivery mode           {self.delivery_mode}',
            f'raw capture             {self.raw_capture}',
            f'redaction               {self.redaction}',
            f'targets                 {", ".join(self.targets)}',
            f'dry run                 {self.dry_run}',
        ]


def _require_enum[E: StrEnum](enum_cls: type[E], key_path: str, value: object) -> E:
    if not isinstance(value, str):
        raise ConfigError(key_path, f'expected a string, got {type(value).__name__}')
    try:
        return enum_cls(value)
    except ValueError:
        options = ', '.join(member.value for member in enum_cls)
        raise ConfigError(key_path, f'{value!r} is not one of: {options}') from None


def load_config_document(path: PathLike[str] | str) -> Mapping[str, object]:
    raw_path = Path(path)
    try:
        document = tomllib.loads(raw_path.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(str(raw_path), f'invalid TOML: {error}') from error

    version = document.get('schema_version')
    if version != SCHEMA_VERSION:
        raise ConfigError('schema_version', f'expected {SCHEMA_VERSION}, got {version!r}')
    return document


def _document_delivery_mode(document: Mapping[str, object]) -> DeliveryMode | None:
    orchestration = document.get('orchestration')
    if not isinstance(orchestration, dict):
        return None
    value = orchestration.get('delivery_mode')
    if value is None:
        return None
    return _require_enum(DeliveryMode, 'orchestration.delivery_mode', value)


def _document_ledger_field[E: StrEnum](
    document: Mapping[str, object], field_name: str, enum_cls: type[E]
) -> E | None:
    ledger = document.get('ledger')
    if not isinstance(ledger, dict):
        return None
    value = ledger.get(field_name)
    if value is None:
        return None
    return _require_enum(enum_cls, f'ledger.{field_name}', value)


def resolve(
    unresolved: UnresolvedConfig, document: Mapping[str, object] | None = None
) -> ResolvedConfig:
    document = document or {}
    agentmaster_home = unresolved.agentmaster_home or DEFAULT_AGENTMASTER_HOME
    delivery_mode = (
        unresolved.delivery_mode
        or _document_delivery_mode(document)
        or DeliveryMode.LOCAL
    )
    raw_capture = (
        _document_ledger_field(document, 'raw_output', RawCapture) or RawCapture.FAILURES
    )
    redaction = (
        _document_ledger_field(document, 'redaction', RedactionMode)
        or RedactionMode.STANDARD
    )
    return ResolvedConfig(
        targets=unresolved.target.expand(),
        dry_run=unresolved.dry_run,
        no_input=unresolved.no_input,
        claude_dir=unresolved.claude_dir,
        copilot_dir=unresolved.copilot_dir,
        agentmaster_home=agentmaster_home,
        ledger_path=unresolved.ledger_path or (agentmaster_home / 'ledger.sqlite3'),
        artifact_path=unresolved.artifact_dir or (agentmaster_home / 'artifacts'),
        ledger_enabled=not unresolved.no_ledger,
        delivery_mode=delivery_mode,
        raw_capture=raw_capture,
        redaction=redaction,
    )


def validate_ledger_flags(unresolved: UnresolvedConfig) -> None:
    if unresolved.no_ledger and unresolved.ledger_path is not None:
        raise ConfigError('--no-ledger', 'cannot be combined with --ledger-path')


_CLAUDE_TARGET_FIELDS = (
    'claude_model',
    'claude_orchestrator_model',
    'claude_orchestrator_effort',
    'claude_implementer_model',
    'claude_implementer_effort',
    'claude_review_model',
    'claude_review_effort',
)
_COPILOT_TARGET_FIELDS = ('copilot_model', 'copilot_implementer_model')


def validate_role_flags(unresolved: UnresolvedConfig) -> None:
    targets = set(unresolved.target.expand())
    if Target.CLAUDE not in targets:
        _reject_present(unresolved, _CLAUDE_TARGET_FIELDS, 'claude')
    if Target.COPILOT not in targets:
        _reject_present(unresolved, _COPILOT_TARGET_FIELDS, 'copilot')


def _reject_present(
    unresolved: UnresolvedConfig, field_names: tuple[str, ...], target_name: str
) -> None:
    for name in field_names:
        if getattr(unresolved, name) is not None:
            flag = f'--{name.replace("_", "-")}'
            raise ConfigError(flag, f'requires --target {target_name} or all')


def validate_auto_compact_flags(unresolved: UnresolvedConfig) -> None:
    percent = unresolved.auto_compact_percent
    if percent is not None:
        if not 1 <= percent <= 100:
            raise ConfigError(
                '--auto-compact-percent', 'must be an integer from 1 through 100'
            )
        if unresolved.clear_auto_compact_override:
            raise ConfigError(
                '--auto-compact-percent',
                'cannot be combined with --clear-auto-compact-override',
            )
    if Target.CLAUDE in set(unresolved.target.expand()):
        return
    if percent is not None:
        raise ConfigError('--auto-compact-percent', 'requires --target claude or all')
    if unresolved.clear_auto_compact_override:
        raise ConfigError(
            '--clear-auto-compact-override', 'requires --target claude or all'
        )


class AutoCompactOverride(NamedTuple):
    percent: int | None
    clear: bool


def resolve_auto_compact(
    *,
    explicit_percent: int | None,
    explicit_clear: bool,
    no_input: bool,
    is_tty: bool,
    prompt: Callable[[], tuple[int | None, bool]] | None = None,
) -> AutoCompactOverride:
    if explicit_percent is not None or explicit_clear:
        return AutoCompactOverride(explicit_percent, explicit_clear)
    if is_tty and not no_input and prompt is not None:
        return AutoCompactOverride(*prompt())
    return AutoCompactOverride(None, False)


class RolePromptContext(NamedTuple):
    no_input: bool
    is_tty: bool
    prompt: (
        Callable[[Role, Target, str, Effort | None], tuple[str, Effort | None]] | None
    ) = None


def resolve_role(
    role: Role,
    target: Target,
    *,
    explicit_model: str | None,
    explicit_effort: Effort | None,
    context: RolePromptContext,
) -> RoleOverride:
    default_model = DEFAULT_ROLE_MODEL[(target, role)]
    default_effort = DEFAULT_ROLE_EFFORT.get(role)
    if explicit_model or explicit_effort:
        model = explicit_model or default_model
        effort = explicit_effort or default_effort
        return RoleOverride(model=model, effort=effort)
    if context.is_tty and not context.no_input and context.prompt is not None:
        model, effort = context.prompt(role, target, default_model, default_effort)
        return RoleOverride(model=model, effort=effort)
    return RoleOverride(model=default_model, effort=default_effort)

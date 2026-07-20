"""Installer configuration domain: typed records and pure resolution logic.

`UnresolvedConfig` mirrors the CLI surface one flag at a time; `resolve()`
applies precedence (CLI > `--config` TOML > built-in default) and produces a
`ResolvedConfig` ready to act on. Everything here is plain data and pure
functions — no filesystem or TTY access — so tests exercise resolution
without a subprocess. `argparse.Namespace` stays at the CLI boundary in
install.py; only `Namespace -> UnresolvedConfig` crosses it.
"""

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
    """An install destination, or `ALL` for every supported destination."""

    CLAUDE = 'claude'
    COPILOT = 'copilot'
    ALL = 'all'

    def expand(self) -> tuple[Target, ...]:
        """Return the concrete targets this value covers."""
        return (Target.CLAUDE, Target.COPILOT) if self is Target.ALL else (self,)


class Role(StrEnum):
    """An Agentmaster runtime role, independently configurable (SPEC.md §11.1)."""

    COORDINATOR = 'coordinator'
    ORCHESTRATOR = 'orchestrator'
    IMPLEMENTER = 'implementer'
    REVIEWER = 'reviewer'


class Effort(StrEnum):
    """A supported reasoning-effort level for a Claude role."""

    LOW = 'low'
    MEDIUM = 'medium'
    HIGH = 'high'
    XHIGH = 'xhigh'
    MAX = 'max'


# Recommended defaults (SPEC.md §11.1). Copilot has no orchestrator/reviewer
# flags and never gets an effort field.
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
    """How Agentmaster is permitted to publish a run's changes."""

    LOCAL = 'local'
    COMMIT = 'commit'
    PULL_REQUEST = 'pull-request'
    MERGE = 'merge'


class RawCapture(StrEnum):
    """Raw request/response and command-output capture policy (§16.2)."""

    FAILURES = 'failures'


class RedactionMode(StrEnum):
    """Redaction policy applied before any raw payload is persisted (§16.2)."""

    STANDARD = 'standard'


class ConfigError(ValueError):
    """A resolved or `--config`-loaded value is invalid.

    Parameters
    ----------
    key_path
        Dotted CLI or TOML location (e.g. ``orchestration.delivery_mode``) so
        the error names exactly which field to fix.
    message
        Human-readable reason.
    """

    def __init__(self, key_path: str, message: str) -> None:
        self.key_path = key_path
        super().__init__(f'{key_path}: {message}')


@dataclass(frozen=True, slots=True)
class RoleOverride:
    """A resolved model — and, where the role supports it, effort — for one role."""

    model: str
    effort: Effort | None = None

    def frontmatter_fields(self) -> dict[str, str]:
        """Allow-listed frontmatter overrides for `installer.frontmatter`."""
        fields = {'model': self.model}
        if self.effort is not None:
            fields['effort'] = self.effort.value
        return fields


@dataclass(frozen=True, slots=True)
class UnresolvedConfig:
    """Raw installer inputs, one field per CLI flag, before precedence applies."""

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
    """Resolved Claude role configuration for one install."""

    coordinator_model: str
    orchestrator: RoleOverride
    implementer: RoleOverride
    reviewer: RoleOverride


@dataclass(frozen=True, slots=True)
class CopilotRoleConfig:
    """Resolved Copilot role configuration for one install."""

    coordinator_model: str
    implementer_model: str


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    """Fully resolved installer configuration — no further precedence to apply."""

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
        """Render the resolved plan for display before any write happens."""
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
    """Parse a `--config` TOML file and validate its schema version.

    Only the fields this installer version resolves are validated here;
    unrecognized tables/keys are left untouched for forward compatibility
    (§12: "Unknown keys must survive a read/modify/write").

    Raises
    ------
    ConfigError
        If the file is not valid TOML or `schema_version` is missing/invalid.
    """
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
    """Apply CLI > `--config` TOML > built-in default precedence.

    `document` is the already-loaded and schema-validated TOML mapping (see
    `load_config_document`), or `None` when `--config` was not given.
    """
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
    """Reject `--no-ledger` combined with `--ledger-path` (SPEC.md §11).

    Raises
    ------
    ConfigError
        Both flags were given; disabling the ledger and pointing it
        somewhere are mutually exclusive.
    """
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
    """Reject a role/target-specific flag when its target isn't selected.

    Raises
    ------
    ConfigError
        A `--claude-*` flag was given without `claude` selected, or a
        `--copilot-*` flag was given without `copilot` selected.
    """
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
    """Reject an invalid percentage, both flags together, or a non-Claude target.

    Raises
    ------
    ConfigError
        `--auto-compact-percent` is outside 1..100, `--auto-compact-percent`
        and `--clear-auto-compact-override` were both given, or either was
        given without `claude` selected (SPEC.md §15).
    """
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
    """Resolved Claude auto-compact percent/clear intent for one install."""

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
    """Resolve the Claude auto-compact percent/clear intent for one install.

    An explicit flag always wins; otherwise an interactive prompt runs when
    available; otherwise noninteractive install preserves current behavior
    (`None, False`) per SPEC.md §15.
    """
    if explicit_percent is not None or explicit_clear:
        return AutoCompactOverride(explicit_percent, explicit_clear)
    if is_tty and not no_input and prompt is not None:
        return AutoCompactOverride(*prompt())
    return AutoCompactOverride(None, False)


class RolePromptContext(NamedTuple):
    """Prompting collaborators shared by every `resolve_role()` call in one install.

    `is_tty` and `prompt` are explicit collaborators (not `sys.stdin.isatty()`
    or `input()` called internally) so tests drive both branches without a
    real terminal. `no_input` and a non-interactive `is_tty=False` both
    suppress prompting.
    """

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
    """Resolve one role's model (and effort, where supported): explicit flag,
    else prompt, else the recommended default (SPEC.md §11.1).
    """
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

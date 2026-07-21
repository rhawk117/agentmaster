"""Tests for ledger-aware installer planning (SPEC.md §11, §15, §16.1).

Covers `installer.config` ledger/artifact/delivery-mode/auto-compact
resolution and `installer.ledger_bootstrap`'s idempotent, permission-safe,
schema-aware placeholder bootstrap. CLI-surface (subprocess) coverage lives
in tests/test_cli.py.
"""

import sqlite3
import stat

import pytest

from installer.config import (
    ConfigError,
    DeliveryMode,
    Target,
    UnresolvedConfig,
    resolve,
    resolve_auto_compact,
    validate_auto_compact_flags,
    validate_ledger_flags,
)
from installer.ledger_bootstrap import (
    SUPPORTED_SCHEMA_VERSION,
    LedgerBootstrapError,
    LedgerBootstrapPlan,
    bootstrap,
)


def _unresolved(**overrides) -> UnresolvedConfig:
    fields: dict = {'target': Target.ALL}
    fields.update(overrides)
    return UnresolvedConfig(**fields)


def test_resolve_defaults_ledger_and_artifact_paths_under_agentmaster_home(tmp_path):
    resolved = resolve(_unresolved(agentmaster_home=tmp_path))

    assert resolved.ledger_path == tmp_path / 'ledger.sqlite3'
    assert resolved.artifact_path == tmp_path / 'artifacts'
    assert resolved.ledger_enabled is True


def test_resolve_ledger_path_override(tmp_path):
    custom = tmp_path / 'custom.sqlite3'
    resolved = resolve(_unresolved(agentmaster_home=tmp_path, ledger_path=custom))

    assert resolved.ledger_path == custom


def test_resolve_artifact_dir_override(tmp_path):
    custom = tmp_path / 'custom-artifacts'
    resolved = resolve(_unresolved(agentmaster_home=tmp_path, artifact_dir=custom))

    assert resolved.artifact_path == custom


def test_resolve_no_ledger_disables_ledger_but_paths_remain_unambiguous(tmp_path):
    resolved = resolve(_unresolved(agentmaster_home=tmp_path, no_ledger=True))

    assert resolved.ledger_enabled is False
    assert resolved.ledger_path == tmp_path / 'ledger.sqlite3'


def test_resolve_delivery_mode_cli_overrides_document(tmp_path):
    document = {'orchestration': {'delivery_mode': 'commit'}}
    resolved = resolve(
        _unresolved(agentmaster_home=tmp_path, delivery_mode=DeliveryMode.MERGE), document
    )

    assert resolved.delivery_mode is DeliveryMode.MERGE


def test_summary_lines_reports_disabled_ledger(tmp_path):
    resolved = resolve(_unresolved(agentmaster_home=tmp_path, no_ledger=True))

    lines = '\n'.join(resolved.summary_lines())

    assert 'ledger                  disabled' in lines
    assert 'artifacts               disabled' in lines


def test_validate_ledger_flags_rejects_no_ledger_with_ledger_path(tmp_path):
    unresolved = _unresolved(no_ledger=True, ledger_path=tmp_path / 'ledger.sqlite3')

    with pytest.raises(ConfigError, match='no-ledger'):
        validate_ledger_flags(unresolved)


def test_validate_ledger_flags_accepts_no_ledger_alone():
    validate_ledger_flags(_unresolved(no_ledger=True))  # no raise


def test_validate_ledger_flags_accepts_ledger_path_alone(tmp_path):
    validate_ledger_flags(
        _unresolved(ledger_path=tmp_path / 'ledger.sqlite3')
    )  # no raise


def _plan(tmp_path) -> LedgerBootstrapPlan:
    return LedgerBootstrapPlan(
        ledger_path=tmp_path / 'agentmaster' / 'ledger.sqlite3',
        artifact_path=tmp_path / 'agentmaster' / 'artifacts',
    )


@pytest.mark.sqlite
def test_bootstrap_creates_ledger_db_and_artifact_dir_with_safe_permissions(tmp_path):
    plan = _plan(tmp_path)

    bootstrap(plan, dry_run=False)

    assert plan.ledger_path.is_file()
    assert plan.artifact_path.is_dir()
    assert stat.S_IMODE(plan.ledger_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(plan.ledger_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(plan.artifact_path.stat().st_mode) == 0o700


@pytest.mark.sqlite
def test_bootstrap_is_idempotent(tmp_path):
    plan = _plan(tmp_path)

    bootstrap(plan, dry_run=False)
    bootstrap(plan, dry_run=False)  # no raise, no error re-creating

    assert plan.ledger_path.is_file()


def test_bootstrap_dry_run_creates_nothing(tmp_path):
    plan = _plan(tmp_path)

    bootstrap(plan, dry_run=True)

    assert not plan.ledger_path.exists()
    assert not plan.artifact_path.exists()


@pytest.mark.sqlite
def test_bootstrap_refuses_newer_schema(tmp_path):
    plan = _plan(tmp_path)
    plan.ledger_path.parent.mkdir(parents=True)
    connection = sqlite3.connect(plan.ledger_path)
    connection.execute(f'PRAGMA user_version = {SUPPORTED_SCHEMA_VERSION + 1}')
    connection.commit()
    connection.close()

    with pytest.raises(LedgerBootstrapError, match='newer than supported'):
        bootstrap(plan, dry_run=False)

    assert not plan.artifact_path.exists()


def test_validate_auto_compact_flags_rejects_percent_out_of_range():
    unresolved = _unresolved(target=Target.CLAUDE, auto_compact_percent=0)

    with pytest.raises(ConfigError, match='auto-compact-percent'):
        validate_auto_compact_flags(unresolved)

    unresolved = _unresolved(target=Target.CLAUDE, auto_compact_percent=101)
    with pytest.raises(ConfigError, match='auto-compact-percent'):
        validate_auto_compact_flags(unresolved)


def test_validate_auto_compact_flags_accepts_boundary_values():
    validate_auto_compact_flags(
        _unresolved(target=Target.CLAUDE, auto_compact_percent=1)
    )  # no raise
    validate_auto_compact_flags(
        _unresolved(target=Target.CLAUDE, auto_compact_percent=100)
    )  # no raise


def test_validate_auto_compact_flags_rejects_percent_with_clear():
    unresolved = _unresolved(
        target=Target.CLAUDE, auto_compact_percent=50, clear_auto_compact_override=True
    )

    with pytest.raises(ConfigError, match='auto-compact-percent'):
        validate_auto_compact_flags(unresolved)


def test_validate_auto_compact_flags_rejects_percent_without_claude_target():
    unresolved = _unresolved(target=Target.COPILOT, auto_compact_percent=50)

    with pytest.raises(ConfigError, match='auto-compact-percent'):
        validate_auto_compact_flags(unresolved)


def test_validate_auto_compact_flags_rejects_clear_without_claude_target():
    unresolved = _unresolved(target=Target.COPILOT, clear_auto_compact_override=True)

    with pytest.raises(ConfigError, match='clear-auto-compact-override'):
        validate_auto_compact_flags(unresolved)


def test_resolve_auto_compact_explicit_percent_wins():
    percent, clear = resolve_auto_compact(
        explicit_percent=50,
        explicit_clear=False,
        no_input=False,
        is_tty=True,
        prompt=lambda: (99, False),
    )

    assert (percent, clear) == (50, False)


def test_resolve_auto_compact_noninteractive_preserves_behavior():
    percent, clear = resolve_auto_compact(
        explicit_percent=None, explicit_clear=False, no_input=True, is_tty=True
    )

    assert (percent, clear) == (None, False)


def test_resolve_auto_compact_prompts_when_interactive():
    percent, clear = resolve_auto_compact(
        explicit_percent=None,
        explicit_clear=False,
        no_input=False,
        is_tty=True,
        prompt=lambda: (75, False),
    )

    assert (percent, clear) == (75, False)


@pytest.mark.sqlite
def test_bootstrap_dry_run_still_validates_existing_newer_schema(tmp_path):
    plan = _plan(tmp_path)
    plan.ledger_path.parent.mkdir(parents=True)
    connection = sqlite3.connect(plan.ledger_path)
    connection.execute(f'PRAGMA user_version = {SUPPORTED_SCHEMA_VERSION + 1}')
    connection.commit()
    connection.close()

    with pytest.raises(LedgerBootstrapError):
        bootstrap(plan, dry_run=True)

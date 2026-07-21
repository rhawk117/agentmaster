"""Tests for the Agentmaster config.toml parse/validate/render logic."""

import pytest

from installer.agentmaster_config import (
    AgentmasterConfigError,
    AgentmasterConfigPlan,
    render_config,
    validate_document,
)


def _plan(**overrides) -> AgentmasterConfigPlan:
    fields = {
        'ledger_path': '/home/user/.agentmaster/ledger.sqlite3',
        'artifact_path': '/home/user/.agentmaster/artifacts',
        'ledger_enabled': True,
        'delivery_mode': 'local',
        'orchestrator_model': 'sonnet',
        'orchestrator_effort': 'medium',
        'implementer_model': 'sonnet',
        'implementer_effort': 'medium',
        'reviewer_model': 'opus',
        'reviewer_effort': 'high',
        'raw_capture': 'failures',
        'redaction': 'standard',
    }
    fields.update(overrides)
    return AgentmasterConfigPlan(**fields)


def test_render_config_fresh_document_has_all_managed_tables():
    text = render_config(_plan(), existing_text=None)

    assert 'schema_version = 1' in text
    assert '[paths]' in text
    assert '[orchestration]' in text
    assert 'delivery_mode = "local"' in text
    assert '[agents.claude.orchestrator]' in text
    assert '[agents.claude.implementer]' in text
    assert '[agents.claude.reviewer]' in text
    assert '[ledger]' in text
    assert 'model = "opus"' in text
    assert 'effort = "high"' in text


def test_render_config_preserves_unmanaged_table_verbatim():
    existing = (
        'schema_version = 1\n\n'
        '[paths]\n'
        'ledger = "/old/ledger.sqlite3"\n\n'
        '[memory]\n'
        'default_visibility = "project"\n'
        'minimum_promotion_evidence = 2\n'
    )

    text = render_config(_plan(delivery_mode='commit'), existing_text=existing)

    assert 'delivery_mode = "commit"' in text
    assert '[memory]' in text
    assert 'default_visibility = "project"' in text
    assert 'minimum_promotion_evidence = 2' in text


def test_render_config_renders_ledger_enabled_flag():
    text = render_config(_plan(ledger_enabled=False), existing_text=None)

    assert 'enabled = false' in text


def test_render_config_drops_managed_table_stale_values():
    existing = 'schema_version = 1\n\n[paths]\nledger = "/old/path.sqlite3"\n'

    text = render_config(_plan(ledger_path='/new/path.sqlite3'), existing_text=existing)

    assert '/old/path.sqlite3' not in text
    assert '/new/path.sqlite3' in text


def test_render_config_rejects_invalid_existing_schema_version():
    existing = 'schema_version = 99\n'

    with pytest.raises(AgentmasterConfigError, match='schema_version'):
        render_config(_plan(), existing_text=existing)


def test_render_config_rejects_malformed_toml():
    with pytest.raises(AgentmasterConfigError, match='invalid TOML'):
        render_config(_plan(), existing_text='not [ valid toml')


def test_validate_document_accepts_well_formed_document():
    document = {
        'schema_version': 1,
        'paths': {'ledger': 'x'},
        'orchestration': {'delivery_mode': 'local'},
    }

    validate_document(document)  # no raise


def test_validate_document_rejects_missing_schema_version():
    with pytest.raises(AgentmasterConfigError, match='schema_version'):
        validate_document({})


def test_validate_document_rejects_non_table_managed_value():
    with pytest.raises(AgentmasterConfigError, match='paths'):
        validate_document({'schema_version': 1, 'paths': 'not-a-table'})


def test_validate_document_rejects_non_table_nested_managed_value():
    with pytest.raises(AgentmasterConfigError, match=r'agents\.claude\.orchestrator'):
        validate_document({'schema_version': 1, 'agents': {'claude': 'not-a-table'}})

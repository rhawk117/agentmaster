"""Tests for MODEL_CALL token accounting (SPEC.md §23 Microtask 12, §17.1)."""

import sqlite3

import pytest

from ledger.connection import connect
from ledger.migrations import migrate

_CREATED_AT = '2026-07-20T00:00:00Z'


@pytest.mark.sqlite
def test_token_dimensions_remain_distinct(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_agent_session(connection)

    connection.execute(
        'INSERT INTO MODEL_CALL '
        '(id, agent_session_id, model, input_tokens, output_tokens, '
        'reasoning_tokens, cache_read_tokens, cache_write_tokens, billed_tokens, '
        'context_estimate_tokens, created_at) '
        "VALUES ('call-1', 'session-1', 'sonnet', 10, 20, 30, 40, 50, 60, 70, ?)",
        (_CREATED_AT,),
    )
    connection.commit()

    row = connection.execute(
        'SELECT input_tokens, output_tokens, reasoning_tokens, cache_read_tokens, '
        'cache_write_tokens, billed_tokens, context_estimate_tokens '
        "FROM MODEL_CALL WHERE id = 'call-1'"
    ).fetchone()

    assert row == (10, 20, 30, 40, 50, 60, 70)
    connection.close()


@pytest.mark.sqlite
def test_missing_usage_is_not_fabricated(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_agent_session(connection)

    connection.execute(
        'INSERT INTO MODEL_CALL (id, agent_session_id, model, created_at) '
        "VALUES ('call-1', 'session-1', 'sonnet', ?)",
        (_CREATED_AT,),
    )
    connection.commit()

    row = connection.execute(
        'SELECT input_tokens, output_tokens, cost_micro_usd '
        "FROM MODEL_CALL WHERE id = 'call-1'"
    ).fetchone()

    assert row == (None, None, None)
    connection.close()


@pytest.mark.sqlite
def test_negative_token_counts_are_rejected(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_agent_session(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO MODEL_CALL '
            '(id, agent_session_id, model, input_tokens, created_at) '
            "VALUES ('call-1', 'session-1', 'sonnet', -1, ?)",
            (_CREATED_AT,),
        )
    connection.close()


@pytest.mark.sqlite
def test_duplicate_provider_call_delivery_cannot_double_count(tmp_path):
    connection = connect(tmp_path / 'ledger.sqlite3')
    migrate(connection)
    _seed_agent_session(connection)
    connection.execute(
        'INSERT INTO MODEL_CALL '
        '(id, agent_session_id, provider_call_id, model, created_at) '
        "VALUES ('call-1', 'session-1', 'provider-event-1', 'sonnet', ?)",
        (_CREATED_AT,),
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            'INSERT INTO MODEL_CALL '
            '(id, agent_session_id, provider_call_id, model, created_at) '
            "VALUES ('call-2', 'session-1', 'provider-event-1', 'sonnet', ?)",
            (_CREATED_AT,),
        )
    connection.close()


def _seed_agent_session(connection: sqlite3.Connection) -> None:
    connection.execute(
        'INSERT INTO PROJECT (id, canonical_root, fingerprint, created_at, last_seen_at) '
        "VALUES ('project-1', '/repo', 'fp-1', ?, ?)",
        (_CREATED_AT, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO USER_SESSION (user_session_id, harness_session_id, created_at) '
        "VALUES ('user-session-1', 'harness-1', ?)",
        (_CREATED_AT,),
    )
    connection.execute(
        'INSERT INTO RUN '
        '(id, project_id, user_session_id, delivery_mode, state, started_at) '
        "VALUES ('run-1', 'project-1', 'user-session-1', 'local', 'Planned', ?)",
        (_CREATED_AT,),
    )
    connection.execute(
        'INSERT INTO AGENT_SESSION '
        '(id, run_id, role, provider, model, state, started_at) '
        "VALUES ('session-1', 'run-1', 'implementer', 'claude', 'sonnet', 'running', ?)",
        (_CREATED_AT,),
    )
    connection.commit()

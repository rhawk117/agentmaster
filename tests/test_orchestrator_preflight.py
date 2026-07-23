import uuid

import pytest

from ledger.orchestrator_preflight import (
    PREFLIGHT_CATEGORIES,
    PreflightCheck,
    run_preflight,
)
from ledger.orchestrator_state import RunTransitionInput, transition_run
from tests.conftest import seed_project_run_task


def _now() -> str:
    return '2026-07-21T00:00:00Z'


def _id() -> str:
    return str(uuid.uuid4())


def _passing_checks() -> tuple[PreflightCheck, ...]:
    return tuple(PreflightCheck(name=name, passed=True) for name in PREFLIGHT_CATEGORIES)


@pytest.mark.sqlite
def test_run_preflight_advances_to_executing_when_every_check_passes(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    transition_run(
        ledger_connection,
        seed.run_id,
        'Preflight',
        RunTransitionInput(now=_now(), id_factory=_id),
    )

    result = run_preflight(
        ledger_connection, seed.run_id, _passing_checks(), now=_now(), id_factory=_id
    )

    assert result.passed is True
    assert result.blocked_reason is None
    state = ledger_connection.execute(
        'SELECT state FROM RUN WHERE id = ?', (seed.run_id,)
    ).fetchone()[0]
    assert state == 'Executing'


@pytest.mark.sqlite
def test_run_preflight_blocks_the_run_when_a_check_fails(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    transition_run(
        ledger_connection,
        seed.run_id,
        'Preflight',
        RunTransitionInput(now=_now(), id_factory=_id),
    )
    checks = tuple(
        PreflightCheck(name=name, passed=name != 'tools', detail='git missing')
        if name == 'tools'
        else PreflightCheck(name=name, passed=True)
        for name in PREFLIGHT_CATEGORIES
    )

    result = run_preflight(
        ledger_connection, seed.run_id, checks, now=_now(), id_factory=_id
    )

    assert result.passed is False
    assert result.blocked_reason is not None
    assert 'tools' in result.blocked_reason
    assert 'git missing' in result.blocked_reason
    row = ledger_connection.execute(
        'SELECT state, blocked_reason FROM RUN WHERE id = ?', (seed.run_id,)
    ).fetchone()
    assert row[0] == 'Blocked'
    assert 'tools' in row[1]


@pytest.mark.sqlite
def test_run_preflight_rejects_an_incomplete_check_set(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    transition_run(
        ledger_connection,
        seed.run_id,
        'Preflight',
        RunTransitionInput(now=_now(), id_factory=_id),
    )
    incomplete = tuple(
        check for check in _passing_checks() if check.name != 'ledger_health'
    )

    with pytest.raises(ValueError, match='ledger_health'):
        run_preflight(
            ledger_connection, seed.run_id, incomplete, now=_now(), id_factory=_id
        )

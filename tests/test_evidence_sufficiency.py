"""Tests for §9.4 evidence sufficiency: every criterion evidenced or excused."""

import json

import pytest
from conftest import seed_project_run_task

from ledger.evidence_sufficiency import (
    TaskNotFoundError,
    check_evidence_sufficiency,
    parse_acceptance_criteria,
)

_CREATED_AT = '2026-07-20T00:00:00Z'


def _set_acceptance(connection, task_id, criteria):
    connection.execute(
        'UPDATE TASK SET acceptance_json = ? WHERE id = ?',
        (json.dumps(criteria), task_id),
    )
    connection.commit()


def _insert_evidence_row(connection, *, evidence_id, task_id, criterion_id):
    artifact_id = f'artifact-{evidence_id}'
    connection.execute(
        'INSERT INTO ARTIFACT '
        '(id, project_id, sha256, media_type, byte_size, relative_path, '
        'retention_class, redaction_state, created_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            artifact_id,
            'project-1',
            f'sha-{evidence_id}',
            'text/plain',
            1,
            'path',
            'standard',
            'redacted',
            _CREATED_AT,
        ),
    )
    connection.execute(
        'INSERT INTO EVIDENCE '
        '(id, run_id, task_id, artifact_id, evidence_kind, criterion_id, created_at) '
        "VALUES (?, 'run-1', ?, ?, 'command-result', ?, ?)",
        (evidence_id, task_id, artifact_id, criterion_id, _CREATED_AT),
    )
    connection.commit()


def test_parse_acceptance_criteria_returns_empty_for_no_acceptance_json():
    assert parse_acceptance_criteria(None) == ()


def test_parse_acceptance_criteria_reads_id_text_and_manual_verification_reason():
    raw = json.dumps([
        {'id': 'c1', 'text': 'does the thing'},
        {
            'id': 'c2',
            'text': 'manual only',
            'manual_verification_reason': 'no CLI exists',
        },
    ])

    criteria = parse_acceptance_criteria(raw)

    assert criteria[0].criterion_id == 'c1'
    assert criteria[0].manual_verification_reason is None
    assert criteria[1].manual_verification_reason == 'no CLI exists'


@pytest.mark.sqlite
def test_check_evidence_sufficiency_is_sufficient_when_every_criterion_has_evidence(
    ledger_connection,
):
    seed_project_run_task(ledger_connection)
    _set_acceptance(ledger_connection, 'task-1', [{'id': 'c1', 'text': 'does the thing'}])
    _insert_evidence_row(
        ledger_connection, evidence_id='evidence-1', task_id='task-1', criterion_id='c1'
    )

    result = check_evidence_sufficiency(ledger_connection, 'task-1')

    assert result.sufficient is True
    assert result.gaps == ()


@pytest.mark.sqlite
def test_check_evidence_sufficiency_is_sufficient_with_an_explicit_manual_reason(
    ledger_connection,
):
    seed_project_run_task(ledger_connection)
    _set_acceptance(
        ledger_connection,
        'task-1',
        [
            {
                'id': 'c1',
                'text': 'manual only',
                'manual_verification_reason': 'no CLI exists',
            }
        ],
    )

    result = check_evidence_sufficiency(ledger_connection, 'task-1')

    assert result.sufficient is True
    assert result.gaps == ()


@pytest.mark.sqlite
def test_check_evidence_sufficiency_reports_a_gap_for_an_unevidenced_criterion(
    ledger_connection,
):
    seed_project_run_task(ledger_connection)
    _set_acceptance(ledger_connection, 'task-1', [{'id': 'c1', 'text': 'does the thing'}])

    result = check_evidence_sufficiency(ledger_connection, 'task-1')

    assert result.sufficient is False
    assert result.gaps[0].criterion_id == 'c1'


@pytest.mark.sqlite
def test_check_evidence_sufficiency_reports_only_the_unevidenced_criteria(
    ledger_connection,
):
    seed_project_run_task(ledger_connection)
    _set_acceptance(
        ledger_connection,
        'task-1',
        [{'id': 'c1', 'text': 'evidenced'}, {'id': 'c2', 'text': 'not evidenced'}],
    )
    _insert_evidence_row(
        ledger_connection, evidence_id='evidence-1', task_id='task-1', criterion_id='c1'
    )

    result = check_evidence_sufficiency(ledger_connection, 'task-1')

    assert result.sufficient is False
    assert [gap.criterion_id for gap in result.gaps] == ['c2']


@pytest.mark.sqlite
def test_check_evidence_sufficiency_rejects_an_unknown_task(ledger_connection):
    seed_project_run_task(ledger_connection)

    with pytest.raises(TaskNotFoundError):
        check_evidence_sufficiency(ledger_connection, 'no-such-task')

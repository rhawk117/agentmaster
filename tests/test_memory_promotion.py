"""End-to-end memory promotion/demotion tests (SPEC.md §17.4, §18, §23 M23).

Exercises the full path a memory travels: a retrospective proposes a
project-scoped Candidate, an independent session validates and activates it,
and only independent cross-project evidence unlocks global promotion --
never the retrospective or the proposing session itself (SPEC.md §1/§5: no
silent self-rewriting).
"""

from typing import TYPE_CHECKING

import pytest
from conftest import LEDGER_SEED_CREATED_AT, seed_project_run_task

from ledger.improvement_policy import (
    MemoryNotEligibleForGlobalPromotionError,
    PromotionThresholds,
    has_harm_signal,
    promote_to_global_scope,
)
from ledger.memory_service import activate_memory, reject_memory, validate_memory
from ledger.retrospective import MemoryCandidateProposal, propose_memory_candidate

if TYPE_CHECKING:
    import sqlite3

_CREATED_AT = LEDGER_SEED_CREATED_AT


def _seed_retrospective_observation(
    connection: sqlite3.Connection, *, run_id: str, retrospective_id: str = 'retro-1'
) -> str:
    connection.execute(
        'INSERT INTO RETROSPECTIVE (id, run_id, status, created_at) '
        "VALUES (?, ?, 'Complete', ?)",
        (retrospective_id, run_id, _CREATED_AT),
    )
    observation_id = f'{retrospective_id}-obs-1'
    connection.execute(
        'INSERT INTO RETRO_OBSERVATION '
        '(id, retrospective_id, observation_kind, claim, created_at) '
        "VALUES (?, ?, 'outcome', 'claim', ?)",
        (observation_id, retrospective_id, _CREATED_AT),
    )
    connection.commit()
    return observation_id


def _seed_evidence(
    connection: sqlite3.Connection,
    *,
    evidence_id: str,
    run_id: str,
    project_id: str,
) -> None:
    artifact_id = f'artifact-{evidence_id}'
    connection.execute(
        'INSERT INTO ARTIFACT (id, project_id, sha256, media_type, byte_size, '
        'relative_path, retention_class, redaction_state, created_at) '
        "VALUES (?, ?, ?, 'text/plain', 1, 'p', 'standard', 'clean', ?)",
        (artifact_id, project_id, f'sha-{evidence_id}', _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO EVIDENCE (id, run_id, artifact_id, evidence_kind, created_at) '
        "VALUES (?, ?, ?, 'command-result', ?)",
        (evidence_id, run_id, artifact_id, _CREATED_AT),
    )
    connection.commit()


def _seed_second_project_run(
    connection: sqlite3.Connection, *, project_id: str, run_id: str
) -> None:
    connection.execute(
        'INSERT INTO PROJECT (id, canonical_root, fingerprint, created_at, last_seen_at) '
        'VALUES (?, ?, ?, ?, ?)',
        (project_id, f'/{project_id}', f'fp-{project_id}', _CREATED_AT, _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO USER_SESSION (user_session_id, harness_session_id, created_at) '
        'VALUES (?, ?, ?)',
        (f'user-session-{run_id}', f'harness-{run_id}', _CREATED_AT),
    )
    connection.execute(
        'INSERT INTO RUN (id, project_id, user_session_id, delivery_mode, state, '
        "started_at) VALUES (?, ?, ?, 'local', 'Planned', ?)",
        (run_id, project_id, f'user-session-{run_id}', _CREATED_AT),
    )
    connection.commit()


def _seed_agent_session(
    connection: sqlite3.Connection, *, agent_session_id: str, run_id: str
) -> None:
    connection.execute(
        'INSERT INTO AGENT_SESSION '
        '(id, run_id, role, provider, model, state, started_at) '
        "VALUES (?, ?, 'implementer', 'anthropic', 'claude-sonnet', 'complete', ?)",
        (agent_session_id, run_id, _CREATED_AT),
    )
    connection.commit()


@pytest.mark.sqlite
def test_a_candidate_proposed_by_a_retrospective_is_project_scoped_only(
    ledger_connection,
):
    seed = seed_project_run_task(ledger_connection)
    observation_id = _seed_retrospective_observation(
        ledger_connection, run_id=seed.run_id
    )
    _seed_evidence(
        ledger_connection,
        evidence_id='evidence-1',
        run_id=seed.run_id,
        project_id=seed.project_id,
    )

    memory_id = propose_memory_candidate(
        ledger_connection,
        MemoryCandidateProposal(
            memory_id='memory-1',
            project_id=seed.project_id,
            memory_kind='lesson',
            title='title',
            content='content',
            observation_id=observation_id,
            evidence_id='evidence-1',
        ),
        created_at=_CREATED_AT,
    )

    scope_rows = ledger_connection.execute(
        'SELECT scope_kind FROM MEMORY_SCOPE WHERE memory_id = ?', (memory_id,)
    ).fetchall()
    assert scope_rows == [('project',)]


@pytest.mark.sqlite
def test_full_promotion_path_from_candidate_to_global_scope(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    observation_id = _seed_retrospective_observation(
        ledger_connection, run_id=seed.run_id
    )
    _seed_evidence(
        ledger_connection,
        evidence_id='evidence-1',
        run_id=seed.run_id,
        project_id=seed.project_id,
    )
    _seed_agent_session(
        ledger_connection, agent_session_id='proposer-session', run_id=seed.run_id
    )
    _seed_agent_session(
        ledger_connection, agent_session_id='validator-session', run_id=seed.run_id
    )

    memory_id = propose_memory_candidate(
        ledger_connection,
        MemoryCandidateProposal(
            memory_id='memory-1',
            project_id=seed.project_id,
            memory_kind='lesson',
            title='title',
            content='content',
            observation_id=observation_id,
            evidence_id='evidence-1',
            proposing_session_id='proposer-session',
        ),
        created_at=_CREATED_AT,
    )

    # Validated and activated at project scope, by a different session.
    validate_memory(
        ledger_connection,
        memory_id,
        'evidence-1',
        updated_at=_CREATED_AT,
        validating_session_id='validator-session',
    )
    activate_memory(ledger_connection, memory_id, updated_at=_CREATED_AT)

    # A second project's independent evidence unlocks global promotion.
    _seed_second_project_run(ledger_connection, project_id='project-2', run_id='run-2')
    _seed_evidence(
        ledger_connection,
        evidence_id='evidence-2',
        run_id='run-2',
        project_id='project-2',
    )
    ledger_connection.execute(
        'INSERT INTO MEMORY_EVIDENCE (memory_id, evidence_id, relation, created_at) '
        "VALUES (?, 'evidence-2', 'supports', ?)",
        (memory_id, _CREATED_AT),
    )
    ledger_connection.commit()

    decision = promote_to_global_scope(
        ledger_connection, memory_id, PromotionThresholds(), created_at=_CREATED_AT
    )

    assert decision.decision == 'eligible'
    scope_kinds = {
        row[0]
        for row in ledger_connection.execute(
            'SELECT scope_kind FROM MEMORY_SCOPE WHERE memory_id = ?', (memory_id,)
        ).fetchall()
    }
    assert scope_kinds == {'project', 'global'}


@pytest.mark.sqlite
def test_promote_to_global_scope_refuses_a_memory_still_scoped_to_one_project(
    ledger_connection,
):
    seed = seed_project_run_task(ledger_connection)
    ledger_connection.execute(
        'INSERT INTO MEMORY '
        '(id, origin_project_id, state, memory_kind, title, content, created_at, '
        'updated_at) '
        "VALUES ('memory-1', ?, 'Active', 'lesson', 'title', 'content', ?, ?)",
        (seed.project_id, _CREATED_AT, _CREATED_AT),
    )
    ledger_connection.commit()

    with pytest.raises(MemoryNotEligibleForGlobalPromotionError):
        promote_to_global_scope(
            ledger_connection, 'memory-1', PromotionThresholds(), created_at=_CREATED_AT
        )


@pytest.mark.sqlite
def test_promote_to_global_scope_refuses_a_memory_not_yet_active(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    ledger_connection.execute(
        'INSERT INTO MEMORY '
        '(id, origin_project_id, state, memory_kind, title, content, created_at, '
        'updated_at) '
        "VALUES ('memory-1', ?, 'Candidate', 'lesson', 'title', 'content', ?, ?)",
        (seed.project_id, _CREATED_AT, _CREATED_AT),
    )
    ledger_connection.commit()

    with pytest.raises(MemoryNotEligibleForGlobalPromotionError):
        promote_to_global_scope(
            ledger_connection, 'memory-1', PromotionThresholds(), created_at=_CREATED_AT
        )


@pytest.mark.sqlite
def test_has_harm_signal_flags_a_memory_with_a_harmful_count(ledger_connection):
    seed = seed_project_run_task(ledger_connection)
    ledger_connection.execute(
        'INSERT INTO MEMORY '
        '(id, origin_project_id, state, memory_kind, title, content, harmful_count, '
        'created_at, updated_at) '
        "VALUES ('memory-1', ?, 'Active', 'lesson', 'title', 'content', 1, ?, ?)",
        (seed.project_id, _CREATED_AT, _CREATED_AT),
    )
    ledger_connection.commit()

    assert has_harm_signal(ledger_connection, 'memory-1') is True


@pytest.mark.sqlite
def test_a_harmful_memory_can_be_demoted_via_the_existing_reject_transition(
    ledger_connection,
):
    seed = seed_project_run_task(ledger_connection)
    ledger_connection.execute(
        'INSERT INTO MEMORY '
        '(id, origin_project_id, state, memory_kind, title, content, harmful_count, '
        'created_at, updated_at) '
        "VALUES ('memory-1', ?, 'Active', 'lesson', 'title', 'content', 2, ?, ?)",
        (seed.project_id, _CREATED_AT, _CREATED_AT),
    )
    ledger_connection.commit()
    assert has_harm_signal(ledger_connection, 'memory-1') is True

    reject_memory(ledger_connection, 'memory-1', updated_at=_CREATED_AT)

    (state,) = ledger_connection.execute(
        "SELECT state FROM MEMORY WHERE id = 'memory-1'"
    ).fetchone()
    assert state == 'Rejected'

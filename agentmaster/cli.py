"""The unified `agentmaster` command surface (SPEC.md §19, §23 Microtask 16).

Parses arguments and formats JSON/text output only; all ledger reads/writes
live in `ledger.*` modules so they stay directly testable without a
subprocess. `ledger.cli` still owns init/migrate/backup/doctor; this module
delegates to it and adds the remaining §19 ledger/memory/context verbs.
"""

import argparse
import json
import sys
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ledger import cli as ledger_cli
from ledger.artifact_store import ArtifactStore
from ledger.connection import connect, connect_read_only
from ledger.context_pack import (
    ContextPackRequest,
    RunNotFoundError,
    SessionScopeError,
    TaskNotFoundError,
    build_context_pack,
)
from ledger.delivery import (
    CiCheckInput,
    DeliveryAttemptInput,
    record_ci_check,
    record_delivery_attempt,
    update_delivery_attempt_head,
    update_delivery_attempt_state,
)
from ledger.delivery_gate import (
    DeliveryAttemptNotFoundError,
    advance_on_green_ci,
    evaluate_merge_gate,
)
from ledger.feedback import FeedbackInput, UnknownReferenceError, record_feedback
from ledger.feedback_capture import register_feedback_capture_hook
from ledger.git_publisher import (
    GhCliClient,
    GitPublisherError,
    MergeRequest,
    PublicationManifest,
    PullRequestRef,
    merge_pull_request,
    publish,
)
from ledger.ingestion import ingest_pending_events
from ledger.legacy_migration import import_legacy_workspace
from ledger.memory_service import (
    IllegalMemoryTransitionError,
    MemoryAccessLog,
    MemoryNotFoundError,
    MemorySearchScope,
    NewMemoryInput,
    activate_memory,
    reject_memory,
    search_memories,
    show_memory,
    supersede_memory,
    validate_memory,
)
from ledger.orchestrator_state import RunTransitionInput, transition_run
from ledger.queries import query_entrypoints, query_runs, query_tokens
from ledger.retrospective import (
    MemoryCandidateProposal,
    RetrospectiveClock,
    RunNotReadyForRetrospectiveError,
    propose_memory_candidate,
    run_retrospective,
)
from ledger.review import (
    MalformedReviewError,
    RecordReviewInput,
    ReviewFindingInput,
    ReviewResult,
)
from ledger.review_gate import (
    DeliveryAttemptNotFoundError as ReviewDeliveryAttemptNotFoundError,
)
from ledger.review_gate import ReviewGateInput, apply_review_result
from ledger.risk_routing import (
    ImplementerScoutPolicy,
    RiskFactors,
    authorize_implementer_scout,
    classify_risk,
    route_task,
)
from ledger.worth import compute_memory_worth, compute_procedure_worth, compute_run_worth

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

    from ledger.git_publisher import GitHubClient


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _emit(*, json_output: bool, payload: object, text_lines: list[str]) -> None:
    if json_output:
        print(json.dumps(payload))
        return
    for line in text_lines:
        print(line)


# --- ledger group ----------------------------------------------------------


def _cmd_ledger_init(args: argparse.Namespace) -> int:
    return ledger_cli.cmd_init(Path(args.path))


def _cmd_ledger_migrate(args: argparse.Namespace) -> int:
    return ledger_cli.cmd_migrate(Path(args.path))


def _cmd_ledger_backup(args: argparse.Namespace) -> int:
    return ledger_cli.cmd_backup(Path(args.path), Path(args.destination))


def _cmd_ledger_doctor(args: argparse.Namespace) -> int:
    return ledger_cli.cmd_doctor(Path(args.path), json_output=args.json_output)


def _cmd_ledger_record_feedback(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    feedback = FeedbackInput(
        id=str(uuid.uuid4()),
        user_session_id=args.user_session_id,
        run_id=args.run_id,
        rating=args.rating,
        created_at=_now(),
        task_id=args.task_id,
        memory_id=args.memory_id,
        comment=args.comment,
    )
    try:
        record_feedback(connection, feedback)
    except (ValueError, UnknownReferenceError) as error:
        print(f'ledger record-feedback: {error}', file=sys.stderr)
        return 1
    finally:
        connection.close()
    print(feedback.id)
    return 0


def _cmd_ledger_query_entrypoints(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        rows = query_entrypoints(connection)
    finally:
        connection.close()
    text_lines = (
        ['no entrypoints recorded']
        if not rows
        else [
            f'{row.kind:8} {row.name:24} active={row.active} {row.source_path or ""}'
            for row in rows
        ]
    )
    _emit(
        json_output=args.json_output,
        payload=[asdict(row) for row in rows],
        text_lines=text_lines,
    )
    return 0


def _cmd_ledger_query_runs(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        rows = query_runs(connection)
    finally:
        connection.close()
    text_lines = (
        ['no runs recorded']
        if not rows
        else [
            f'{row.run_id} [{row.state}] {row.delivery_mode} '
            f'tasks={row.completed_task_count}/{row.task_count}'
            for row in rows
        ]
    )
    _emit(
        json_output=args.json_output,
        payload=[asdict(row) for row in rows],
        text_lines=text_lines,
    )
    return 0


def _cmd_ledger_query_tokens(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        rows = query_tokens(connection, run_id=args.run_id)
    finally:
        connection.close()
    text_lines = (
        ['no token usage recorded']
        if not rows
        else [
            f'{row.run_id} {row.model} calls={row.call_count} '
            f'input={row.input_tokens} output={row.output_tokens}'
            for row in rows
        ]
    )
    _emit(
        json_output=args.json_output,
        payload=[asdict(row) for row in rows],
        text_lines=text_lines,
    )
    return 0


def _cmd_ledger_query(args: argparse.Namespace) -> int:
    if args.query_target == 'runs':
        return _cmd_ledger_query_runs(args)
    if args.query_target == 'tokens':
        return _cmd_ledger_query_tokens(args)
    return _cmd_ledger_query_entrypoints(args)


def _cmd_ledger_ingest_events(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        report = ingest_pending_events(
            connection,
            Path(args.spool),
            id_factory=lambda: str(uuid.uuid4()),
            now=_now,
        )
    finally:
        connection.close()
    _emit(
        json_output=args.json_output,
        payload=asdict(report),
        text_lines=[
            f'ingested={report.ingested} malformed={report.malformed} '
            f'unsupported={report.unsupported} failed={report.failed}'
        ],
    )
    return 0


# --- migrate group -----------------------------------------------------------


def _cmd_migrate_legacy_files(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        reports = import_legacy_workspace(
            connection,
            Path(args.workspace),
            id_factory=lambda: str(uuid.uuid4()),
            now=_now,
            apply=not args.dry_run,
        )
    finally:
        connection.close()
    payload = [
        {
            'source': str(report.source),
            'imported': report.imported,
            'ambiguous': report.ambiguous,
            'malformed': report.malformed,
            'redacted': report.redacted,
            'artifact_id': report.artifact_id,
        }
        for report in reports
    ]
    text_lines = (
        ['no legacy telemetry files found']
        if not reports
        else [
            f'{report.source}: imported={report.imported} ambiguous={report.ambiguous} '
            f'malformed={report.malformed} redacted={report.redacted}'
            for report in reports
        ]
    )
    _emit(json_output=args.json_output, payload=payload, text_lines=text_lines)
    return 0


# --- memory group ------------------------------------------------------------


def _cmd_memory_search(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        scope = MemorySearchScope(
            project_id=args.project_id,
            run_id=args.run_id,
            task_id=args.task_id,
            agent_session_id=args.agent_session_id,
        )
        results = search_memories(
            connection,
            scope,
            args.query,
            MemoryAccessLog(
                access_id_factory=lambda: str(uuid.uuid4()), created_at=_now()
            ),
            limit=args.limit,
        )
    finally:
        connection.close()
    text_lines = (
        ['no matching memories']
        if not results
        else [
            f'#{result.rank} {result.memory_id} score={result.score:.3f} '
            f'tokens~{result.estimated_tokens} {result.title}'
            for result in results
        ]
    )
    _emit(
        json_output=args.json_output,
        payload=[asdict(result) for result in results],
        text_lines=text_lines,
    )
    return 0


def _cmd_memory_show(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        detail = show_memory(connection, args.memory_id)
    finally:
        connection.close()
    if detail is None:
        print(f'memory {args.memory_id!r} not found', file=sys.stderr)
        return 1
    _emit(
        json_output=args.json_output,
        payload=asdict(detail),
        text_lines=[
            f'{detail.memory_id} [{detail.state}] {detail.title}',
            detail.content,
        ],
    )
    return 0


def _cmd_memory_validate(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        validate_memory(
            connection,
            args.memory_id,
            args.evidence_id,
            updated_at=_now(),
            validating_session_id=args.validating_session_id,
        )
    except (MemoryNotFoundError, IllegalMemoryTransitionError) as error:
        print(f'memory validate: {error}', file=sys.stderr)
        return 1
    finally:
        connection.close()
    return 0


def _cmd_memory_activate(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        activate_memory(connection, args.memory_id, updated_at=_now())
    except (MemoryNotFoundError, IllegalMemoryTransitionError) as error:
        print(f'memory activate: {error}', file=sys.stderr)
        return 1
    finally:
        connection.close()
    return 0


def _cmd_memory_reject(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        reject_memory(connection, args.memory_id, updated_at=_now())
    except (MemoryNotFoundError, IllegalMemoryTransitionError) as error:
        print(f'memory reject: {error}', file=sys.stderr)
        return 1
    finally:
        connection.close()
    return 0


def _cmd_memory_supersede(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    new_memory = NewMemoryInput(
        id=args.new_memory_id,
        origin_project_id=args.project_id,
        memory_kind=args.memory_kind,
        title=args.title,
        content=args.content,
        confidence=args.confidence,
    )
    try:
        supersede_memory(connection, args.old_memory_id, new_memory, updated_at=_now())
    except (MemoryNotFoundError, IllegalMemoryTransitionError) as error:
        print(f'memory supersede: {error}', file=sys.stderr)
        return 1
    finally:
        connection.close()
    print(new_memory.id)
    return 0


# --- context group -----------------------------------------------------------


def _cmd_context_build(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        request = ContextPackRequest(
            project_id=args.project_id,
            user_session_id=args.user_session_id,
            run_id=args.run_id,
            task_id=args.task_id,
            budget_tokens=args.budget_tokens,
            query=args.query,
        )
        pack = build_context_pack(connection, request, created_at=_now())
    except (SessionScopeError, RunNotFoundError, TaskNotFoundError) as error:
        print(f'context build: {error}', file=sys.stderr)
        return 1
    finally:
        connection.close()
    text_lines = [
        f'task {pack.task_id}: {pack.objective}',
        f'budget {pack.estimated_tokens}/{pack.budget_tokens} tokens',
        *[f'  #{m.rank} {m.memory_id} {m.title}' for m in pack.selected_memories],
    ]
    if pack.stop_conditions:
        text_lines.append(f'stop conditions: {", ".join(pack.stop_conditions)}')
    text_lines.append(f'digest {pack.digest}')
    _emit(json_output=args.json_output, payload=asdict(pack), text_lines=text_lines)
    return 0


def _cmd_context_route(args: argparse.Namespace) -> int:
    factors = RiskFactors(
        destructive_state=args.destructive_state,
        migration=args.migration,
        auth=args.auth,
        concurrency=args.concurrency,
        release=args.release,
        schema=args.schema,
        public_api=args.public_api,
        large_change_surface=args.large_change_surface,
    )
    risk_classification = classify_risk(factors)
    decision = route_task(factors, ambiguous=args.ambiguous)

    payload: dict[str, object] = {
        'risk_classification': risk_classification,
        **asdict(decision),
    }
    text_lines = [
        f'route: {decision.route} (risk={decision.risk_level})',
        f'reason: {decision.reason}',
    ]
    if decision.risk_factors:
        text_lines.append(f'risk factors: {", ".join(decision.risk_factors)}')

    if args.requested_scouts > 0:
        policy = ImplementerScoutPolicy(
            enabled=args.implementer_scout_enabled,
            scout_budget_tokens=args.implementer_scout_budget_tokens,
        )
        authorization = authorize_implementer_scout(policy, args.requested_scouts)
        payload['scout_authorization'] = asdict(authorization)
        text_lines.append(
            f'scout authorization: authorized={authorization.authorized} '
            f'max_scouts={authorization.max_scouts} reason={authorization.reason}'
        )

    _emit(json_output=args.json_output, payload=payload, text_lines=text_lines)
    return 0


# --- delivery group ----------------------------------------------------------


def _default_github_client(args: argparse.Namespace) -> GitHubClient:
    """Return the `GitHubClient` a delivery command uses; tests monkeypatch this."""
    del args
    return GhCliClient()


def _delivery_attempt_row(
    connection: sqlite3.Connection, delivery_attempt_id: str
) -> tuple:
    row = connection.execute(
        'SELECT run_id, branch, head_sha, pr_number, pr_url FROM DELIVERY_ATTEMPT '
        'WHERE id = ?',
        (delivery_attempt_id,),
    ).fetchone()
    if row is None:
        raise DeliveryAttemptNotFoundError(delivery_attempt_id)
    return row


def _cmd_delivery_prepare_pr(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    manifest = PublicationManifest(
        repo_path=Path(args.repo),
        base_branch=args.base_branch,
        base_sha=args.base_sha,
        feature_branch=args.feature_branch,
        allowed_paths=tuple(args.allowed_path),
        commit_message=args.commit_message,
        pr_title=args.pr_title,
        pr_body=args.pr_body,
        expected_dirty_paths=tuple(args.expected_dirty_path),
        evidence_links=tuple(args.evidence_link),
        reviewers=tuple(args.reviewer),
        merge_strategy=args.merge_strategy,
        delete_branch_on_merge=not args.no_delete_branch,
    )
    try:
        result = publish(manifest, _default_github_client(args))
    except GitPublisherError as error:
        print(f'delivery prepare-pr: {error}', file=sys.stderr)
        return 1
    finally:
        connection.close()

    connection = connect(Path(args.path))
    try:
        delivery = DeliveryAttemptInput(
            id=str(uuid.uuid4()),
            run_id=args.run_id,
            branch=manifest.feature_branch,
            base_sha=manifest.base_sha,
            head_sha=result.head_sha,
            created_at=_now(),
            pr_number=result.pull_request.number,
            pr_url=result.pull_request.url,
            state='merged' if result.already_merged else 'open',
        )
        attempt_no = record_delivery_attempt(connection, delivery)
    finally:
        connection.close()

    payload = {
        'delivery_attempt_id': delivery.id,
        'attempt_no': attempt_no,
        'head_sha': result.head_sha,
        'pr_number': result.pull_request.number,
        'pr_url': result.pull_request.url,
        'reused_existing_pr': result.reused_existing_pr,
        'already_merged': result.already_merged,
    }
    _emit(
        json_output=args.json_output,
        payload=payload,
        text_lines=[
            f'{delivery.id} attempt#{attempt_no} PR #{result.pull_request.number} '
            f'{result.pull_request.url} head={result.head_sha}'
        ],
    )
    return 0


def _cmd_delivery_watch_ci(args: argparse.Namespace) -> int:
    if args.max_attempts < 1:
        print('delivery watch-ci: --max-attempts must be >= 1', file=sys.stderr)
        return 1
    connection = connect(Path(args.path))
    try:
        run_id, branch, head_sha, _pr_number, _pr_url = _delivery_attempt_row(
            connection, args.delivery_attempt_id
        )
        required_checks = tuple(args.required_check)
        github = _default_github_client(args)
        evaluation = None
        for attempt in range(args.max_attempts):
            live_pr = github.find_pull_request(
                repo_path=Path(args.repo), head_branch=branch
            )
            if live_pr is not None and live_pr.head_sha != head_sha:
                head_sha = live_pr.head_sha
                update_delivery_attempt_head(
                    connection, args.delivery_attempt_id, head_sha
                )
            for observation in github.list_check_runs(
                repo_path=Path(args.repo), head_sha=head_sha
            ):
                record_ci_check(
                    connection,
                    CiCheckInput(
                        id=str(uuid.uuid4()),
                        delivery_attempt_id=args.delivery_attempt_id,
                        name=observation.name,
                        head_sha=observation.head_sha,
                        status=observation.status,
                        conclusion=observation.conclusion,
                        observed_at=_now(),
                        provider_check_id=observation.provider_check_id,
                        url=observation.url,
                    ),
                )
            evaluation = advance_on_green_ci(
                connection,
                run_id,
                args.delivery_attempt_id,
                required_checks,
                RunTransitionInput(now=_now(), id_factory=lambda: str(uuid.uuid4())),
            )
            if evaluation.outcome != 'pending':
                break
            if attempt < args.max_attempts - 1:
                time.sleep(args.poll_interval_seconds)
    except KeyboardInterrupt:
        print('delivery watch-ci: cancelled', file=sys.stderr)
        return 130
    finally:
        connection.close()

    assert evaluation is not None  # guaranteed: max_attempts >= 1, loop always assigns it
    _emit(
        json_output=args.json_output,
        payload=asdict(evaluation),
        text_lines=[
            f'{evaluation.outcome} @ {evaluation.head_sha}',
            *evaluation.blocking_reasons,
        ],
    )
    return {'green': 0, 'failed': 1}.get(evaluation.outcome, 2)


def _cmd_delivery_review_gate(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        result = evaluate_merge_gate(
            connection, args.delivery_attempt_id, tuple(args.required_check)
        )
    except DeliveryAttemptNotFoundError as error:
        print(f'delivery review-gate: {error}', file=sys.stderr)
        return 1
    finally:
        connection.close()
    _emit(
        json_output=args.json_output,
        payload=asdict(result),
        text_lines=[
            f'{"ready" if result.ready else "blocked"} @ {result.head_sha}',
            *result.blocking_reasons,
        ],
    )
    return 0 if result.ready else 1


def _cmd_delivery_merge_gate(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        run_id, _branch, _head_sha, pr_number, pr_url = _delivery_attempt_row(
            connection, args.delivery_attempt_id
        )
        result = evaluate_merge_gate(
            connection, args.delivery_attempt_id, tuple(args.required_check)
        )
        if not result.ready:
            _emit(
                json_output=args.json_output,
                payload=asdict(result),
                text_lines=['blocked', *result.blocking_reasons],
            )
            return 1

        github = _default_github_client(args)
        pull_request = PullRequestRef(
            number=pr_number, url=pr_url, head_sha=result.head_sha, state='open'
        )
        try:
            merge_pull_request(
                github,
                pull_request,
                MergeRequest(
                    repo_path=Path(args.repo),
                    merge_strategy=args.merge_strategy,
                    delete_branch_on_merge=not args.no_delete_branch,
                    expected_head_sha=result.head_sha,
                ),
            )
        except GitPublisherError as error:
            print(f'delivery merge-gate: {error}', file=sys.stderr)
            return 1

        update_delivery_attempt_state(
            connection, args.delivery_attempt_id, 'merged', completed_at=_now()
        )
        transition_run(
            connection,
            run_id,
            'Merged',
            RunTransitionInput(now=_now(), id_factory=lambda: str(uuid.uuid4())),
        )
    finally:
        connection.close()
    _emit(
        json_output=args.json_output,
        payload={'merged': True, 'head_sha': result.head_sha},
        text_lines=[f'merged @ {result.head_sha}'],
    )
    return 0


def _read_review_result(args: argparse.Namespace) -> ReviewResult:
    """Parse a reviewer's SPEC.md §20.3 JSON result from `--result-file` or stdin."""
    raw = (
        sys.stdin.read()
        if args.result_file == '-'
        else Path(args.result_file).read_text(encoding='utf-8')
    )
    parsed = json.loads(raw)
    findings = tuple(
        ReviewFindingInput(
            severity=finding.get('severity'),
            summary=finding.get('summary'),
            criterion_id=finding.get('criterion_id'),
            file_path=finding.get('file_path'),
            line_no=finding.get('line_no'),
            evidence_id=finding.get('evidence_id'),
        )
        for finding in parsed.get('findings', [])
    )
    return ReviewResult(
        schema_version=parsed.get('schema_version'),
        reviewed_sha=parsed.get('reviewed_sha'),
        verdict=parsed.get('verdict'),
        findings=findings,
        evidence_gaps=tuple(parsed.get('evidence_gaps', [])),
        summary=parsed.get('summary', ''),
    )


def _cmd_delivery_record_review(args: argparse.Namespace) -> int:
    try:
        result = _read_review_result(args)
    except (OSError, json.JSONDecodeError) as error:
        print(f'delivery record-review: {error}', file=sys.stderr)
        return 1

    connection = connect(Path(args.path))
    store = ArtifactStore(Path(args.artifact_root))
    gate_input = ReviewGateInput(
        run_id=args.run_id,
        review_input=RecordReviewInput(
            review_id=str(uuid.uuid4()),
            delivery_attempt_id=args.delivery_attempt_id,
            reviewer_session_id=args.reviewer_session_id,
            project_id=args.project_id,
            now=_now(),
            id_factory=lambda: str(uuid.uuid4()),
        ),
        transition=RunTransitionInput(now=_now(), id_factory=lambda: str(uuid.uuid4())),
    )
    try:
        outcome = apply_review_result(connection, store, gate_input, result)
    except (MalformedReviewError, ReviewDeliveryAttemptNotFoundError) as error:
        print(f'delivery record-review: {error}', file=sys.stderr)
        return 1
    finally:
        connection.close()

    _emit(
        json_output=args.json_output,
        payload=asdict(outcome),
        text_lines=[
            f'{outcome.outcome} [{outcome.run_state}] review={outcome.review_id}',
            *outcome.unresolved_blockers,
        ],
    )
    return 0 if outcome.outcome == 'good' else 1


# --- retro group --------------------------------------------------------------


def _cmd_retro_run(args: argparse.Namespace) -> int:
    register_feedback_capture_hook()
    ledger_path = Path(args.path)
    read_connection = connect_read_only(ledger_path)
    connection = connect(ledger_path)
    try:
        result = run_retrospective(
            connection,
            read_connection,
            args.run_id,
            RetrospectiveClock(now=_now(), id_factory=lambda: str(uuid.uuid4())),
        )
    except RunNotReadyForRetrospectiveError as error:
        print(f'retro run: {error}', file=sys.stderr)
        return 1
    finally:
        connection.close()
        read_connection.close()
    _emit(
        json_output=args.json_output,
        payload=asdict(result),
        text_lines=[f'{result.retrospective_id} [{result.outcome}] {result.summary}'],
    )
    return 0


def _cmd_retro_show(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        retrospective = connection.execute(
            'SELECT id, status, outcome, summary FROM RETROSPECTIVE WHERE run_id = ?',
            (args.run_id,),
        ).fetchone()
        if retrospective is None:
            print(
                f'retro show: no retrospective recorded for run {args.run_id!r}',
                file=sys.stderr,
            )
            return 1
        retrospective_id, status, outcome, summary = retrospective
        observations = connection.execute(
            'SELECT id, observation_kind, claim, confidence, counterfactual '
            'FROM RETRO_OBSERVATION WHERE retrospective_id = ? ORDER BY id',
            (retrospective_id,),
        ).fetchall()
    finally:
        connection.close()
    payload = {
        'retrospective_id': retrospective_id,
        'status': status,
        'outcome': outcome,
        'summary': summary,
        'observations': [
            {
                'id': row[0],
                'observation_kind': row[1],
                'claim': row[2],
                'confidence': row[3],
                'counterfactual': row[4],
            }
            for row in observations
        ],
    }
    _emit(
        json_output=args.json_output,
        payload=payload,
        text_lines=[
            f'{retrospective_id} [{status}] {outcome}: {summary}',
            *[f'  {row[1]}: {row[2]}' for row in observations],
        ],
    )
    return 0


def _cmd_retro_propose(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    proposal = MemoryCandidateProposal(
        memory_id=args.memory_id,
        project_id=args.project_id,
        memory_kind=args.memory_kind,
        title=args.title,
        content=args.content,
        observation_id=args.observation_id,
        evidence_id=args.evidence_id,
        proposing_session_id=args.proposing_session_id,
        confidence=args.confidence,
    )
    try:
        propose_memory_candidate(connection, proposal, created_at=_now())
    finally:
        connection.close()
    print(proposal.memory_id)
    return 0


# --- worth group --------------------------------------------------------------


def _cmd_worth_run(args: argparse.Namespace) -> int:
    connection = connect_read_only(Path(args.path))
    try:
        report = compute_run_worth(connection, args.run_id)
    finally:
        connection.close()
    if report is None:
        print(f'worth run: no run {args.run_id!r} recorded', file=sys.stderr)
        return 1
    _emit(
        json_output=args.json_output,
        payload=asdict(report),
        text_lines=[
            f'{report.run_id} [{report.outcome_state}] '
            f'tasks={report.completed_task_count}/{report.task_count} '
            f'tokens={report.total_input_tokens}+{report.total_output_tokens} '
            f'unresolved_findings={report.unresolved_finding_count}',
        ],
    )
    return 0


def _cmd_worth_memory(args: argparse.Namespace) -> int:
    connection = connect_read_only(Path(args.path))
    try:
        report = compute_memory_worth(connection, args.memory_id)
    finally:
        connection.close()
    _emit(
        json_output=args.json_output,
        payload=asdict(report),
        text_lines=[
            f'{report.memory_id} retrievals={report.retrieval_count} '
            f'helpful={report.helpful_count} harmful={report.harmful_count}',
        ],
    )
    return 0


def _cmd_worth_procedure(args: argparse.Namespace) -> int:
    connection = connect_read_only(Path(args.path))
    try:
        report = compute_procedure_worth(connection, args.procedure_id)
    finally:
        connection.close()
    _emit(
        json_output=args.json_output,
        payload=asdict(report),
        text_lines=[
            f'{report.procedure_id} uses={report.use_count} {report.outcome_counts}'
        ],
    )
    return 0


# --- argument parsing --------------------------------------------------------


def _add_path_argument(cmd: argparse.ArgumentParser) -> None:
    cmd.add_argument('--path', required=True)


def _add_json_argument(cmd: argparse.ArgumentParser) -> None:
    cmd.add_argument('--json', action='store_true', dest='json_output')


def _build_ledger_subparser(sub: argparse._SubParsersAction) -> dict[str, Callable]:
    ledger_parser = sub.add_parser('ledger')
    ledger_sub = ledger_parser.add_subparsers(dest='command', required=True)

    for name in ('init', 'migrate'):
        _add_path_argument(ledger_sub.add_parser(name))

    doctor_cmd = ledger_sub.add_parser('doctor')
    _add_path_argument(doctor_cmd)
    _add_json_argument(doctor_cmd)

    backup_cmd = ledger_sub.add_parser('backup')
    _add_path_argument(backup_cmd)
    backup_cmd.add_argument('--destination', required=True)

    feedback_cmd = ledger_sub.add_parser('record-feedback')
    _add_path_argument(feedback_cmd)
    feedback_cmd.add_argument('--user-session-id', required=True)
    feedback_cmd.add_argument('--run-id', required=True)
    feedback_cmd.add_argument('--rating', type=int, choices=(-1, 0, 1), required=True)
    feedback_cmd.add_argument('--task-id', default=None)
    feedback_cmd.add_argument('--memory-id', default=None)
    feedback_cmd.add_argument('--comment', default=None)

    query_cmd = ledger_sub.add_parser('query')
    query_sub = query_cmd.add_subparsers(dest='query_target', required=True)
    entrypoints_cmd = query_sub.add_parser('entrypoints')
    _add_path_argument(entrypoints_cmd)
    _add_json_argument(entrypoints_cmd)
    runs_cmd = query_sub.add_parser('runs')
    _add_path_argument(runs_cmd)
    _add_json_argument(runs_cmd)
    tokens_cmd = query_sub.add_parser('tokens')
    _add_path_argument(tokens_cmd)
    _add_json_argument(tokens_cmd)
    tokens_cmd.add_argument('--run-id', default=None)

    ingest_events_cmd = ledger_sub.add_parser('ingest-events')
    _add_path_argument(ingest_events_cmd)
    _add_json_argument(ingest_events_cmd)
    ingest_events_cmd.add_argument('--spool', required=True)

    return {
        'init': _cmd_ledger_init,
        'migrate': _cmd_ledger_migrate,
        'backup': _cmd_ledger_backup,
        'doctor': _cmd_ledger_doctor,
        'record-feedback': _cmd_ledger_record_feedback,
        'query': _cmd_ledger_query,
        'ingest-events': _cmd_ledger_ingest_events,
    }


def _build_memory_subparser(sub: argparse._SubParsersAction) -> dict[str, Callable]:
    memory_parser = sub.add_parser('memory')
    memory_sub = memory_parser.add_subparsers(dest='command', required=True)

    search_cmd = memory_sub.add_parser('search')
    _add_path_argument(search_cmd)
    _add_json_argument(search_cmd)
    search_cmd.add_argument('--project-id', required=True)
    search_cmd.add_argument('--run-id', required=True)
    search_cmd.add_argument('--task-id', default=None)
    search_cmd.add_argument('--agent-session-id', default=None)
    search_cmd.add_argument('--query', required=True)
    search_cmd.add_argument('--limit', type=int, default=10)

    show_cmd = memory_sub.add_parser('show')
    _add_path_argument(show_cmd)
    _add_json_argument(show_cmd)
    show_cmd.add_argument('--memory-id', required=True)

    validate_cmd = memory_sub.add_parser('validate')
    _add_path_argument(validate_cmd)
    validate_cmd.add_argument('--memory-id', required=True)
    validate_cmd.add_argument('--evidence-id', required=True)
    validate_cmd.add_argument('--validating-session-id', required=True)

    activate_cmd = memory_sub.add_parser('activate')
    _add_path_argument(activate_cmd)
    activate_cmd.add_argument('--memory-id', required=True)

    reject_cmd = memory_sub.add_parser('reject')
    _add_path_argument(reject_cmd)
    reject_cmd.add_argument('--memory-id', required=True)

    supersede_cmd = memory_sub.add_parser('supersede')
    _add_path_argument(supersede_cmd)
    supersede_cmd.add_argument('--old-memory-id', required=True)
    supersede_cmd.add_argument('--new-memory-id', required=True)
    supersede_cmd.add_argument('--project-id', required=True)
    supersede_cmd.add_argument('--memory-kind', required=True)
    supersede_cmd.add_argument('--title', required=True)
    supersede_cmd.add_argument('--content', required=True)
    supersede_cmd.add_argument('--confidence', default=None)

    return {
        'search': _cmd_memory_search,
        'show': _cmd_memory_show,
        'validate': _cmd_memory_validate,
        'activate': _cmd_memory_activate,
        'reject': _cmd_memory_reject,
        'supersede': _cmd_memory_supersede,
    }


def _build_migrate_subparser(sub: argparse._SubParsersAction) -> dict[str, Callable]:
    migrate_parser = sub.add_parser('migrate')
    migrate_sub = migrate_parser.add_subparsers(dest='command', required=True)

    legacy_files_cmd = migrate_sub.add_parser('legacy-files')
    _add_path_argument(legacy_files_cmd)
    _add_json_argument(legacy_files_cmd)
    legacy_files_cmd.add_argument('--workspace', required=True)
    legacy_files_cmd.add_argument('--dry-run', action='store_true')

    return {'legacy-files': _cmd_migrate_legacy_files}


def _build_context_subparser(sub: argparse._SubParsersAction) -> dict[str, Callable]:
    context_parser = sub.add_parser('context')
    context_sub = context_parser.add_subparsers(dest='command', required=True)

    build_cmd = context_sub.add_parser('build')
    _add_path_argument(build_cmd)
    _add_json_argument(build_cmd)
    build_cmd.add_argument('--project-id', required=True)
    build_cmd.add_argument('--user-session-id', required=True)
    build_cmd.add_argument('--run-id', required=True)
    build_cmd.add_argument('--task-id', required=True)
    build_cmd.add_argument('--budget-tokens', type=int, required=True)
    build_cmd.add_argument('--query', default=None)

    route_cmd = context_sub.add_parser('route')
    _add_json_argument(route_cmd)
    route_cmd.add_argument('--destructive-state', action='store_true')
    route_cmd.add_argument('--migration', action='store_true')
    route_cmd.add_argument('--auth', action='store_true')
    route_cmd.add_argument('--concurrency', action='store_true')
    route_cmd.add_argument('--release', action='store_true')
    route_cmd.add_argument('--schema', action='store_true')
    route_cmd.add_argument('--public-api', action='store_true')
    route_cmd.add_argument('--large-change-surface', action='store_true')
    route_cmd.add_argument('--ambiguous', action='store_true')
    route_cmd.add_argument('--requested-scouts', type=int, default=0)
    route_cmd.add_argument('--implementer-scout-enabled', action='store_true')
    route_cmd.add_argument('--implementer-scout-budget-tokens', type=int, default=0)

    return {'build': _cmd_context_build, 'route': _cmd_context_route}


def _add_publication_arguments(cmd: argparse.ArgumentParser) -> None:
    cmd.add_argument('--merge-strategy', default='squash')
    cmd.add_argument('--no-delete-branch', action='store_true')


def _build_delivery_subparser(sub: argparse._SubParsersAction) -> dict[str, Callable]:
    delivery_parser = sub.add_parser('delivery')
    delivery_sub = delivery_parser.add_subparsers(dest='command', required=True)

    prepare_pr_cmd = delivery_sub.add_parser('prepare-pr')
    _add_path_argument(prepare_pr_cmd)
    _add_json_argument(prepare_pr_cmd)
    prepare_pr_cmd.add_argument('--run-id', required=True)
    prepare_pr_cmd.add_argument('--repo', required=True)
    prepare_pr_cmd.add_argument('--base-branch', required=True)
    prepare_pr_cmd.add_argument('--base-sha', required=True)
    prepare_pr_cmd.add_argument('--feature-branch', required=True)
    prepare_pr_cmd.add_argument('--allowed-path', action='append', required=True)
    prepare_pr_cmd.add_argument('--expected-dirty-path', action='append', default=[])
    prepare_pr_cmd.add_argument('--commit-message', required=True)
    prepare_pr_cmd.add_argument('--pr-title', required=True)
    prepare_pr_cmd.add_argument('--pr-body', required=True)
    prepare_pr_cmd.add_argument('--evidence-link', action='append', default=[])
    prepare_pr_cmd.add_argument('--reviewer', action='append', default=[])
    _add_publication_arguments(prepare_pr_cmd)

    watch_ci_cmd = delivery_sub.add_parser('watch-ci')
    _add_path_argument(watch_ci_cmd)
    _add_json_argument(watch_ci_cmd)
    watch_ci_cmd.add_argument('--delivery-attempt-id', required=True)
    watch_ci_cmd.add_argument('--repo', required=True)
    watch_ci_cmd.add_argument('--required-check', action='append', default=[])
    watch_ci_cmd.add_argument('--max-attempts', type=int, default=30)
    watch_ci_cmd.add_argument('--poll-interval-seconds', type=float, default=10.0)

    review_gate_cmd = delivery_sub.add_parser('review-gate')
    _add_path_argument(review_gate_cmd)
    _add_json_argument(review_gate_cmd)
    review_gate_cmd.add_argument('--delivery-attempt-id', required=True)
    review_gate_cmd.add_argument('--required-check', action='append', default=[])

    merge_gate_cmd = delivery_sub.add_parser('merge-gate')
    _add_path_argument(merge_gate_cmd)
    _add_json_argument(merge_gate_cmd)
    merge_gate_cmd.add_argument('--delivery-attempt-id', required=True)
    merge_gate_cmd.add_argument('--repo', required=True)
    merge_gate_cmd.add_argument('--required-check', action='append', default=[])
    _add_publication_arguments(merge_gate_cmd)

    record_review_cmd = delivery_sub.add_parser('record-review')
    _add_path_argument(record_review_cmd)
    _add_json_argument(record_review_cmd)
    record_review_cmd.add_argument('--artifact-root', required=True)
    record_review_cmd.add_argument('--run-id', required=True)
    record_review_cmd.add_argument('--delivery-attempt-id', required=True)
    record_review_cmd.add_argument('--reviewer-session-id', required=True)
    record_review_cmd.add_argument('--project-id', required=True)
    record_review_cmd.add_argument('--result-file', default='-')

    return {
        'prepare-pr': _cmd_delivery_prepare_pr,
        'watch-ci': _cmd_delivery_watch_ci,
        'review-gate': _cmd_delivery_review_gate,
        'merge-gate': _cmd_delivery_merge_gate,
        'record-review': _cmd_delivery_record_review,
    }


def _build_retro_subparser(sub: argparse._SubParsersAction) -> dict[str, Callable]:
    retro_parser = sub.add_parser('retro')
    retro_sub = retro_parser.add_subparsers(dest='command', required=True)

    run_cmd = retro_sub.add_parser('run')
    _add_path_argument(run_cmd)
    _add_json_argument(run_cmd)
    run_cmd.add_argument('--run-id', required=True)

    show_cmd = retro_sub.add_parser('show')
    _add_path_argument(show_cmd)
    _add_json_argument(show_cmd)
    show_cmd.add_argument('--run-id', required=True)

    propose_cmd = retro_sub.add_parser('propose')
    _add_path_argument(propose_cmd)
    propose_cmd.add_argument('--memory-id', required=True)
    propose_cmd.add_argument('--project-id', required=True)
    propose_cmd.add_argument('--memory-kind', required=True)
    propose_cmd.add_argument('--title', required=True)
    propose_cmd.add_argument('--content', required=True)
    propose_cmd.add_argument('--observation-id', required=True)
    propose_cmd.add_argument('--evidence-id', required=True)
    propose_cmd.add_argument('--proposing-session-id', default=None)
    propose_cmd.add_argument('--confidence', default=None)

    return {
        'run': _cmd_retro_run,
        'show': _cmd_retro_show,
        'propose': _cmd_retro_propose,
    }


def _build_worth_subparser(sub: argparse._SubParsersAction) -> dict[str, Callable]:
    worth_parser = sub.add_parser('worth')
    worth_sub = worth_parser.add_subparsers(dest='command', required=True)

    run_cmd = worth_sub.add_parser('run')
    _add_path_argument(run_cmd)
    _add_json_argument(run_cmd)
    run_cmd.add_argument('--run-id', required=True)

    memory_cmd = worth_sub.add_parser('memory')
    _add_path_argument(memory_cmd)
    _add_json_argument(memory_cmd)
    memory_cmd.add_argument('--memory-id', required=True)

    procedure_cmd = worth_sub.add_parser('procedure')
    _add_path_argument(procedure_cmd)
    _add_json_argument(procedure_cmd)
    procedure_cmd.add_argument('--procedure-id', required=True)

    return {
        'run': _cmd_worth_run,
        'memory': _cmd_worth_memory,
        'procedure': _cmd_worth_procedure,
    }


def _build_parser() -> tuple[argparse.ArgumentParser, dict[str, dict[str, Callable]]]:
    parser = argparse.ArgumentParser(prog='agentmaster')
    sub = parser.add_subparsers(dest='group', required=True)
    groups = {
        'ledger': _build_ledger_subparser(sub),
        'memory': _build_memory_subparser(sub),
        'context': _build_context_subparser(sub),
        'migrate': _build_migrate_subparser(sub),
        'delivery': _build_delivery_subparser(sub),
        'retro': _build_retro_subparser(sub),
        'worth': _build_worth_subparser(sub),
    }
    return parser, groups


def main(argv: list[str] | None = None) -> int:
    parser, groups = _build_parser()
    args = parser.parse_args(argv)
    return groups[args.group][args.command](args)


if __name__ == '__main__':
    sys.exit(main())

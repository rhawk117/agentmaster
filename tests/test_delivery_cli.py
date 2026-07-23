import json
import shutil
import subprocess
import uuid

import pytest

import agentmaster.cli as cli_module
from agentmaster.cli import main
from ledger.connection import connect
from ledger.delivery import DeliveryAttemptInput, record_delivery_attempt
from ledger.git_publisher import CreatePullRequestInput, PullRequestRef
from ledger.orchestrator_state import RunTransitionInput, transition_run
from tests.conftest import LEDGER_SEED_CREATED_AT, seed_project_run_task

_resolved_git = shutil.which('git')
assert _resolved_git is not None, 'git executable not found on PATH'
_GIT: str = _resolved_git


class FakeGitHubClient:
    def __init__(self) -> None:
        self.pull_requests: dict[str, PullRequestRef] = {}
        self.check_runs: list = []
        self.merged: list[dict] = []
        self._next_number = 1

    def find_pull_request(self, *, repo_path, head_branch):
        del repo_path
        return self.pull_requests.get(head_branch)

    def create_pull_request(self, request: CreatePullRequestInput) -> PullRequestRef:
        head_sha = _run(request.repo_path, 'rev-parse', request.head)
        ref = PullRequestRef(
            number=self._next_number,
            url=f'https://example.invalid/pr/{self._next_number}',
            head_sha=head_sha,
            state='open',
        )
        self._next_number += 1
        self.pull_requests[request.head] = ref
        return ref

    def list_check_runs(self, *, repo_path, head_sha):
        del repo_path
        return tuple(obs for obs in self.check_runs if obs.head_sha == head_sha)

    def merge_pull_request(self, *, repo_path, number, strategy, delete_branch):
        del repo_path
        self.merged.append({
            'number': number,
            'strategy': strategy,
            'delete_branch': delete_branch,
        })


def _run(repo_path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603
        [_GIT, *args], cwd=repo_path, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _init_repo(path) -> str:
    _run(path, 'init', '-b', 'develop')
    _run(path, 'config', 'user.email', 'test@example.invalid')
    _run(path, 'config', 'user.name', 'Test')
    (path / 'README.md').write_text('base\n', encoding='utf-8')
    _run(path, 'add', 'README.md')
    _run(path, 'commit', '-m', 'chore: initial commit')
    return _run(path, 'rev-parse', 'HEAD')


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / 'repo'
    repo_path.mkdir()
    base_sha = _init_repo(repo_path)
    remote_path = tmp_path / 'origin.git'
    subprocess.run(  # noqa: S603
        [_GIT, 'init', '--bare', str(remote_path)], check=True, capture_output=True
    )
    _run(repo_path, 'remote', 'add', 'origin', str(remote_path))
    _run(repo_path, 'push', 'origin', 'develop')
    return repo_path, base_sha


@pytest.fixture
def ledger_path(tmp_path):
    path = tmp_path / 'ledger.sqlite3'
    assert main(['ledger', 'init', '--path', str(path)]) == 0
    return path


@pytest.fixture
def run_at_ci_pending(ledger_path):
    connection = connect(ledger_path)
    seed = seed_project_run_task(connection)
    for state in ('Preflight', 'Executing', 'Verifying', 'DeliveryPending', 'CIPending'):
        transition_run(
            connection,
            seed.run_id,
            state,
            RunTransitionInput(
                now=LEDGER_SEED_CREATED_AT, id_factory=lambda: str(uuid.uuid4())
            ),
        )
    connection.close()
    return seed.run_id


@pytest.fixture
def github(monkeypatch):
    fake = FakeGitHubClient()
    monkeypatch.setattr(cli_module, '_default_github_client', lambda _args: fake)
    return fake


@pytest.mark.sqlite
def test_prepare_pr_publishes_and_records_a_delivery_attempt(
    capsys, ledger_path, run_at_ci_pending, repo, github
):
    repo_path, base_sha = repo
    (repo_path / 'feature.py').write_text('x = 1\n', encoding='utf-8')

    exit_code = main([
        'delivery',
        'prepare-pr',
        '--path',
        str(ledger_path),
        '--run-id',
        run_at_ci_pending,
        '--repo',
        str(repo_path),
        '--base-branch',
        'develop',
        '--base-sha',
        base_sha,
        '--feature-branch',
        'feat/example',
        '--allowed-path',
        'feature.py',
        '--commit-message',
        'feat: add feature',
        '--pr-title',
        'feat: add feature',
        '--pr-body',
        '## Summary\nadds it\n\nevidence: run-1',
        '--evidence-link',
        'run-1',
        '--json',
    ])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['pr_number'] == 1
    assert github.pull_requests['feat/example'].number == 1
    connection = connect(ledger_path)
    row = connection.execute(
        'SELECT pr_number, state FROM DELIVERY_ATTEMPT WHERE id = ?',
        (payload['delivery_attempt_id'],),
    ).fetchone()
    connection.close()
    assert row == (1, 'open')


@pytest.mark.sqlite
def test_watch_ci_advances_run_to_review_required_on_green(
    capsys, ledger_path, run_at_ci_pending, repo, github
):
    from ledger.delivery import DeliveryAttemptInput, record_delivery_attempt
    from ledger.git_publisher import CheckRunObservation

    repo_path, base_sha = repo
    head_sha = 'a' * 40
    connection = connect(ledger_path)
    delivery = DeliveryAttemptInput(
        id=str(uuid.uuid4()),
        run_id=run_at_ci_pending,
        branch='feat/example',
        base_sha=base_sha,
        head_sha=head_sha,
        created_at=LEDGER_SEED_CREATED_AT,
    )
    record_delivery_attempt(connection, delivery)
    connection.close()
    github.check_runs.append(
        CheckRunObservation(
            name='build', head_sha=head_sha, status='completed', conclusion='success'
        )
    )

    exit_code = main([
        'delivery',
        'watch-ci',
        '--path',
        str(ledger_path),
        '--delivery-attempt-id',
        delivery.id,
        '--repo',
        str(repo_path),
        '--required-check',
        'build',
        '--max-attempts',
        '1',
        '--json',
    ])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['outcome'] == 'green'
    connection = connect(ledger_path)
    state = connection.execute(
        'SELECT state FROM RUN WHERE id = ?', (run_at_ci_pending,)
    ).fetchone()[0]
    connection.close()
    assert state == 'ReviewRequired'


@pytest.mark.sqlite
def test_review_gate_blocks_when_no_review_is_recorded(
    capsys, ledger_path, run_at_ci_pending
):
    from ledger.delivery import DeliveryAttemptInput, record_delivery_attempt

    connection = connect(ledger_path)
    delivery = DeliveryAttemptInput(
        id=str(uuid.uuid4()),
        run_id=run_at_ci_pending,
        branch='feat/example',
        base_sha='0' * 40,
        head_sha='a' * 40,
        created_at=LEDGER_SEED_CREATED_AT,
    )
    record_delivery_attempt(connection, delivery)
    connection.close()

    exit_code = main([
        'delivery',
        'review-gate',
        '--path',
        str(ledger_path),
        '--delivery-attempt-id',
        delivery.id,
        '--json',
    ])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload['ready'] is False


@pytest.mark.sqlite
def test_merge_gate_merges_when_pr_ci_and_review_heads_match(
    capsys, ledger_path, run_at_ci_pending, repo, github
):
    from ledger.delivery import (
        CiCheckInput,
        DeliveryAttemptInput,
        record_ci_check,
        record_delivery_attempt,
    )

    repo_path, _base_sha = repo
    head_sha = 'a' * 40
    connection = connect(ledger_path)
    delivery = DeliveryAttemptInput(
        id=str(uuid.uuid4()),
        run_id=run_at_ci_pending,
        branch='feat/example',
        base_sha='0' * 40,
        head_sha=head_sha,
        created_at=LEDGER_SEED_CREATED_AT,
        pr_number=7,
        pr_url='https://example.invalid/pr/7',
    )
    record_delivery_attempt(connection, delivery)
    record_ci_check(
        connection,
        CiCheckInput(
            id=str(uuid.uuid4()),
            delivery_attempt_id=delivery.id,
            name='build',
            head_sha=head_sha,
            status='completed',
            conclusion='success',
            observed_at=LEDGER_SEED_CREATED_AT,
        ),
    )
    reviewer_session_id = str(uuid.uuid4())
    connection.execute(
        'INSERT INTO AGENT_SESSION '
        '(id, run_id, role, provider, model, state, started_at) '
        "VALUES (?, ?, 'reviewer', 'claude', 'opus', 'active', ?)",
        (reviewer_session_id, run_at_ci_pending, LEDGER_SEED_CREATED_AT),
    )
    connection.execute(
        'INSERT INTO REVIEW '
        '(id, delivery_attempt_id, reviewer_session_id, reviewed_sha, verdict, '
        'created_at) '
        "VALUES (?, ?, ?, ?, 'GOOD', ?)",
        (
            str(uuid.uuid4()),
            delivery.id,
            reviewer_session_id,
            head_sha,
            LEDGER_SEED_CREATED_AT,
        ),
    )
    connection.commit()
    for state in ('ReviewRequired', 'Reviewing', 'MergePending'):
        transition_run(
            connection,
            run_at_ci_pending,
            state,
            RunTransitionInput(
                now=LEDGER_SEED_CREATED_AT, id_factory=lambda: str(uuid.uuid4())
            ),
        )
    connection.close()

    exit_code = main([
        'delivery',
        'merge-gate',
        '--path',
        str(ledger_path),
        '--delivery-attempt-id',
        delivery.id,
        '--repo',
        str(repo_path),
        '--required-check',
        'build',
        '--json',
    ])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['merged'] is True
    assert github.merged == [{'number': 7, 'strategy': 'squash', 'delete_branch': True}]
    connection = connect(ledger_path)
    state = connection.execute(
        'SELECT state FROM DELIVERY_ATTEMPT WHERE id = ?', (delivery.id,)
    ).fetchone()[0]
    run_state = connection.execute(
        'SELECT state FROM RUN WHERE id = ?', (run_at_ci_pending,)
    ).fetchone()[0]
    connection.close()
    assert state == 'merged'
    assert run_state == 'Merged'


@pytest.fixture
def run_reviewing(ledger_path, run_at_ci_pending):
    connection = connect(ledger_path)
    for state in ('ReviewRequired', 'Reviewing'):
        transition_run(
            connection,
            run_at_ci_pending,
            state,
            RunTransitionInput(
                now=LEDGER_SEED_CREATED_AT, id_factory=lambda: str(uuid.uuid4())
            ),
        )
    head_sha = 'a' * 40
    delivery = DeliveryAttemptInput(
        id=str(uuid.uuid4()),
        run_id=run_at_ci_pending,
        branch='feat/example',
        base_sha='0' * 40,
        head_sha=head_sha,
        created_at=LEDGER_SEED_CREATED_AT,
    )
    record_delivery_attempt(connection, delivery)
    reviewer_session_id = str(uuid.uuid4())
    connection.execute(
        'INSERT INTO AGENT_SESSION '
        '(id, run_id, role, provider, model, state, started_at) '
        "VALUES (?, ?, 'reviewer', 'claude', 'opus', 'active', ?)",
        (reviewer_session_id, run_at_ci_pending, LEDGER_SEED_CREATED_AT),
    )
    connection.commit()
    connection.close()
    return run_at_ci_pending, delivery.id, reviewer_session_id, head_sha


def _write_review_result(tmp_path, **overrides):
    payload = {
        'schema_version': 1,
        'reviewed_sha': 'a' * 40,
        'verdict': 'GOOD',
        'findings': [],
        'evidence_gaps': [],
        'summary': 'looks good',
        **overrides,
    }
    result_path = tmp_path / 'review-result.json'
    result_path.write_text(json.dumps(payload), encoding='utf-8')
    return result_path


@pytest.mark.sqlite
def test_record_review_good_persists_and_advances_run_to_merge_pending(
    capsys, tmp_path, ledger_path, run_reviewing
):
    run_id, delivery_attempt_id, reviewer_session_id, head_sha = run_reviewing
    result_path = _write_review_result(tmp_path, reviewed_sha=head_sha, verdict='GOOD')

    exit_code = main([
        'delivery',
        'record-review',
        '--path',
        str(ledger_path),
        '--artifact-root',
        str(tmp_path / 'artifacts'),
        '--run-id',
        run_id,
        '--delivery-attempt-id',
        delivery_attempt_id,
        '--reviewer-session-id',
        reviewer_session_id,
        '--project-id',
        'project-1',
        '--result-file',
        str(result_path),
        '--json',
    ])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['outcome'] == 'good'
    assert payload['run_state'] == 'MergePending'
    connection = connect(ledger_path)
    review_row = connection.execute(
        'SELECT verdict, reviewed_sha FROM REVIEW WHERE id = ?', (payload['review_id'],)
    ).fetchone()
    run_state = connection.execute(
        'SELECT state FROM RUN WHERE id = ?', (run_id,)
    ).fetchone()[0]
    connection.close()
    assert review_row == ('GOOD', head_sha)
    assert run_state == 'MergePending'


@pytest.mark.sqlite
def test_record_review_needs_fixes_persists_findings_and_blocks_the_run(
    capsys, tmp_path, ledger_path, run_reviewing
):
    run_id, delivery_attempt_id, reviewer_session_id, head_sha = run_reviewing
    result_path = _write_review_result(
        tmp_path,
        reviewed_sha=head_sha,
        verdict='NEEDS_FIXES',
        findings=[{'severity': 'blocker', 'summary': 'missing null check'}],
    )

    exit_code = main([
        'delivery',
        'record-review',
        '--path',
        str(ledger_path),
        '--artifact-root',
        str(tmp_path / 'artifacts'),
        '--run-id',
        run_id,
        '--delivery-attempt-id',
        delivery_attempt_id,
        '--reviewer-session-id',
        reviewer_session_id,
        '--project-id',
        'project-1',
        '--result-file',
        str(result_path),
        '--json',
    ])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload['outcome'] == 'needs_fixes'
    assert payload['run_state'] == 'FixesRequired'
    assert payload['unresolved_blockers'] == ['missing null check']
    connection = connect(ledger_path)
    finding_rows = connection.execute(
        'SELECT summary, state FROM REVIEW_FINDING WHERE review_id = ?',
        (payload['review_id'],),
    ).fetchall()
    run_state = connection.execute(
        'SELECT state FROM RUN WHERE id = ?', (run_id,)
    ).fetchone()[0]
    connection.close()
    assert finding_rows == [('missing null check', 'accepted')]
    assert run_state == 'FixesRequired'

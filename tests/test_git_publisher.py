import shutil
import subprocess

import pytest

from ledger.git_publisher import (
    GitCommandError,
    GitPublisherError,
    MergeRequest,
    PublicationManifest,
    PullRequestRef,
    merge_pull_request,
    publish,
    push_branch,
    stage_paths,
)

_resolved_git = shutil.which('git')
assert _resolved_git is not None, 'git executable not found on PATH'
_GIT: str = _resolved_git


class FakeGitHubClient:
    def __init__(self) -> None:
        self.pull_requests: dict[str, PullRequestRef] = {}
        self.created: list[dict] = []
        self.merged: list[dict] = []
        self._next_number = 1

    def find_pull_request(self, *, repo_path, head_branch):
        del repo_path
        return self.pull_requests.get(head_branch)

    def create_pull_request(self, request):
        ref = PullRequestRef(
            number=self._next_number,
            url=f'https://example.invalid/pr/{self._next_number}',
            head_sha=_run(request.repo_path, 'rev-parse', request.head),
            state='open',
        )
        self._next_number += 1
        self.pull_requests[request.head] = ref
        self.created.append({
            'base': request.base,
            'head': request.head,
            'title': request.title,
            'body': request.body,
        })
        return ref

    def list_check_runs(self, *, repo_path, head_sha):
        del repo_path, head_sha
        return ()

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


def _init_bare_remote(tmp_path, repo_path) -> None:
    remote_path = tmp_path / 'origin.git'
    subprocess.run(  # noqa: S603
        [_GIT, 'init', '--bare', str(remote_path)], check=True, capture_output=True
    )
    _run(repo_path, 'remote', 'add', 'origin', str(remote_path))
    _run(repo_path, 'push', 'origin', 'develop')


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / 'repo'
    repo_path.mkdir()
    base_sha = _init_repo(repo_path)
    _init_bare_remote(tmp_path, repo_path)
    return repo_path, base_sha


def _manifest(repo_path, base_sha, **overrides) -> PublicationManifest:
    fields: dict = {
        'repo_path': repo_path,
        'base_branch': 'develop',
        'base_sha': base_sha,
        'feature_branch': 'feat/example',
        'allowed_paths': ('feature.py',),
        'commit_message': 'feat: add feature',
        'pr_title': 'feat: add feature',
        'pr_body': '## Summary\nadds the feature\n\nevidence: run-1',
        'evidence_links': ('run-1',),
    }
    fields.update(overrides)
    return PublicationManifest(**fields)


def _write_feature_file(repo_path) -> None:
    (repo_path / 'feature.py').write_text('x = 1\n', encoding='utf-8')


@pytest.mark.subprocess
def test_publish_stages_commits_pushes_and_opens_a_pr(repo):
    repo_path, base_sha = repo
    _write_feature_file(repo_path)
    manifest = _manifest(repo_path, base_sha)
    github = FakeGitHubClient()

    result = publish(manifest, github)

    assert result.reused_existing_pr is False
    assert result.already_merged is False
    assert github.created[0]['head'] == 'feat/example'
    remote_head = _run(repo_path, 'rev-parse', f'origin/{manifest.feature_branch}')
    assert remote_head == result.head_sha


@pytest.mark.subprocess
def test_publish_refuses_to_stage_a_path_outside_the_manifest(repo):
    repo_path, base_sha = repo
    _write_feature_file(repo_path)
    (repo_path / 'secret.env').write_text('TOKEN=abc\n', encoding='utf-8')
    manifest = _manifest(repo_path, base_sha)
    github = FakeGitHubClient()

    with pytest.raises(GitPublisherError, match='unexpected dirty path'):
        publish(manifest, github)

    assert _run(repo_path, 'log', '--oneline').count('\n') == 0


@pytest.mark.subprocess
def test_stage_paths_never_stages_a_path_not_in_allowed_paths(repo):
    repo_path, base_sha = repo
    _write_feature_file(repo_path)
    manifest = _manifest(
        repo_path, base_sha, allowed_paths=('feature.py',), expected_dirty_paths=()
    )

    staged = stage_paths(manifest)

    assert staged == ('feature.py',)
    status = _run(repo_path, 'status', '--porcelain')
    assert 'feature.py' in status


@pytest.mark.subprocess
def test_push_never_issues_a_force_push_and_a_diverged_remote_is_rejected(repo):
    repo_path, base_sha = repo
    _write_feature_file(repo_path)
    manifest = _manifest(repo_path, base_sha)
    github = FakeGitHubClient()
    publish(manifest, github)

    other_clone = repo_path.parent / 'other-clone'
    subprocess.run(  # noqa: S603
        [_GIT, 'clone', str(repo_path.parent / 'origin.git'), str(other_clone)],
        check=True,
        capture_output=True,
    )
    _run(other_clone, 'checkout', manifest.feature_branch)
    _run(other_clone, 'config', 'user.email', 'other@example.invalid')
    _run(other_clone, 'config', 'user.name', 'Other')
    (other_clone / 'feature.py').write_text('x = 2\n', encoding='utf-8')
    _run(other_clone, 'commit', '-am', 'feat: diverge')
    _run(other_clone, 'push', 'origin', manifest.feature_branch)

    _run(repo_path, 'commit', '--amend', '-m', 'feat: add feature (amended)')

    with pytest.raises(GitCommandError, match=r'non-fast-forward|fetch first|rejected'):
        push_branch(manifest)


@pytest.mark.subprocess
def test_publish_reconciles_an_existing_open_pr_instead_of_duplicating(repo):
    repo_path, base_sha = repo
    _write_feature_file(repo_path)
    manifest = _manifest(repo_path, base_sha)
    github = FakeGitHubClient()

    first = publish(manifest, github)
    second = publish(manifest, github)

    assert first.pull_request.number == second.pull_request.number
    assert second.reused_existing_pr is True
    assert len(github.created) == 1


@pytest.mark.subprocess
def test_publish_short_circuits_when_the_pr_is_already_merged(repo):
    repo_path, base_sha = repo
    _write_feature_file(repo_path)
    manifest = _manifest(repo_path, base_sha)
    github = FakeGitHubClient()
    first = publish(manifest, github)
    github.pull_requests[manifest.feature_branch] = PullRequestRef(
        number=first.pull_request.number,
        url=first.pull_request.url,
        head_sha=first.head_sha,
        state='merged',
    )

    result = publish(manifest, github)

    assert result.already_merged is True
    assert result.head_sha == first.head_sha


@pytest.mark.subprocess
def test_validate_pr_template_rejects_a_body_missing_required_sections(repo):
    repo_path, base_sha = repo
    (repo_path / '.github').mkdir()
    (repo_path / '.github' / 'PULL_REQUEST_TEMPLATE.md').write_text(
        '## Summary\n\n## Verification\n', encoding='utf-8'
    )
    _write_feature_file(repo_path)
    manifest = _manifest(
        repo_path,
        base_sha,
        pr_body='no sections here\nevidence: run-1',
        expected_dirty_paths=('.github/', '.github/PULL_REQUEST_TEMPLATE.md'),
    )
    github = FakeGitHubClient()

    with pytest.raises(GitPublisherError, match='missing required section'):
        publish(manifest, github)


@pytest.mark.subprocess
def test_validate_pr_template_rejects_a_body_missing_evidence_links(repo):
    repo_path, base_sha = repo
    _write_feature_file(repo_path)
    manifest = _manifest(repo_path, base_sha, evidence_links=())
    github = FakeGitHubClient()

    with pytest.raises(GitPublisherError, match='evidence link'):
        publish(manifest, github)


@pytest.mark.subprocess
def test_merge_pull_request_refuses_a_head_mismatch(repo):
    repo_path, base_sha = repo
    _write_feature_file(repo_path)
    manifest = _manifest(repo_path, base_sha)
    github = FakeGitHubClient()
    result = publish(manifest, github)

    with pytest.raises(GitPublisherError, match='refusing to merge'):
        merge_pull_request(
            github,
            result.pull_request,
            MergeRequest(
                repo_path=manifest.repo_path,
                merge_strategy=manifest.merge_strategy,
                delete_branch_on_merge=manifest.delete_branch_on_merge,
                expected_head_sha='f' * 40,
            ),
        )
    assert github.merged == []


@pytest.mark.subprocess
def test_merge_pull_request_merges_on_a_matching_head(repo):
    repo_path, base_sha = repo
    _write_feature_file(repo_path)
    manifest = _manifest(repo_path, base_sha)
    github = FakeGitHubClient()
    result = publish(manifest, github)

    merge_pull_request(
        github,
        result.pull_request,
        MergeRequest(
            repo_path=manifest.repo_path,
            merge_strategy=manifest.merge_strategy,
            delete_branch_on_merge=manifest.delete_branch_on_merge,
            expected_head_sha=result.head_sha,
        ),
    )

    assert github.merged == [
        {
            'number': result.pull_request.number,
            'strategy': 'squash',
            'delete_branch': True,
        }
    ]


@pytest.mark.subprocess
def test_publish_refuses_an_unsafe_branch_name(repo):
    repo_path, base_sha = repo
    _write_feature_file(repo_path)
    manifest = _manifest(repo_path, base_sha, feature_branch='--force')
    github = FakeGitHubClient()

    with pytest.raises(GitPublisherError, match='not a safe git ref name'):
        publish(manifest, github)

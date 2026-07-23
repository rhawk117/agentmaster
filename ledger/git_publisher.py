import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

_SHA_RE = re.compile(r'^[0-9a-f]{40}$')
_UNSAFE_REF_RE = re.compile(r'^-')


class GitPublisherError(ValueError): ...


class GitCommandError(RuntimeError):
    def __init__(self, args: Sequence[str], returncode: int, stderr: str) -> None:
        super().__init__(f'{" ".join(args)!r} exited {returncode}: {stderr.strip()}')
        self.returncode = returncode
        self.stderr = stderr


@dataclass(frozen=True, slots=True)
class PublicationManifest:
    repo_path: Path
    base_branch: str
    base_sha: str
    feature_branch: str
    allowed_paths: tuple[str, ...]
    commit_message: str
    pr_title: str
    pr_body: str
    expected_dirty_paths: tuple[str, ...] = ()
    evidence_links: tuple[str, ...] = ()
    reviewers: tuple[str, ...] = ()
    merge_strategy: str = 'squash'
    delete_branch_on_merge: bool = True


@dataclass(frozen=True, slots=True)
class PullRequestRef:
    number: int
    url: str
    head_sha: str
    state: str


@dataclass(frozen=True, slots=True)
class CreatePullRequestInput:
    repo_path: Path
    base: str
    head: str
    title: str
    body: str
    reviewers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CheckRunObservation:
    name: str
    head_sha: str
    status: str
    conclusion: str | None
    provider_check_id: str | None = None
    url: str | None = None


class GitHubClient(Protocol):
    def find_pull_request(
        self, *, repo_path: Path, head_branch: str
    ) -> PullRequestRef | None: ...

    def create_pull_request(self, request: CreatePullRequestInput) -> PullRequestRef: ...

    def list_check_runs(
        self, *, repo_path: Path, head_sha: str
    ) -> tuple[CheckRunObservation, ...]: ...

    def merge_pull_request(
        self,
        *,
        repo_path: Path,
        number: int,
        strategy: str,
        delete_branch: bool,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class PublicationResult:
    head_sha: str
    pull_request: PullRequestRef
    reused_existing_pr: bool
    already_merged: bool


def _git_executable() -> str:
    resolved = shutil.which('git')
    if resolved is None:
        raise GitCommandError(('git',), -1, 'git executable not found on PATH')
    return resolved


def _run_git(repo_path: Path, *args: str) -> str:
    argv = (_git_executable(), *args)
    result = subprocess.run(  # noqa: S603
        argv,
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GitCommandError(argv, result.returncode, result.stderr)
    return result.stdout


def _validate_ref(value: str, *, field: str) -> None:
    if not value or _UNSAFE_REF_RE.match(value):
        raise GitPublisherError(f'{field} {value!r} is not a safe git ref name')


def _validate_manifest(manifest: PublicationManifest) -> None:
    _validate_ref(manifest.base_branch, field='base_branch')
    _validate_ref(manifest.feature_branch, field='feature_branch')
    if not _SHA_RE.fullmatch(manifest.base_sha):
        raise GitPublisherError(f'base_sha {manifest.base_sha!r} is not a 40-hex SHA')
    if not manifest.allowed_paths:
        raise GitPublisherError('allowed_paths must not be empty')
    if not manifest.commit_message:
        raise GitPublisherError('commit_message must not be empty')
    if not manifest.pr_title or not manifest.pr_body:
        raise GitPublisherError('pr_title and pr_body must not be empty')


def _status_paths(repo_path: Path) -> tuple[str, ...]:
    output = _run_git(repo_path, 'status', '--porcelain')
    paths: list[str] = []
    for line in output.splitlines():
        if not line:
            continue
        path = line[3:].split(' -> ')[-1].strip()
        paths.append(path)
    return tuple(paths)


def verify_expected_dirty_paths(manifest: PublicationManifest) -> tuple[str, ...]:
    permitted = set(manifest.allowed_paths) | set(manifest.expected_dirty_paths)
    dirty = _status_paths(manifest.repo_path)
    unexpected = [path for path in dirty if path not in permitted]
    if unexpected:
        raise GitPublisherError(
            f'unexpected dirty path(s), refusing to stage: {unexpected}'
        )
    return dirty


def checkout_feature_branch(manifest: PublicationManifest) -> None:
    existing = _run_git(
        manifest.repo_path, 'branch', '--list', manifest.feature_branch
    ).strip()
    if existing:
        _run_git(manifest.repo_path, 'checkout', manifest.feature_branch)
    else:
        _run_git(manifest.repo_path, 'checkout', '-b', manifest.feature_branch)


def stage_paths(manifest: PublicationManifest) -> tuple[str, ...]:
    dirty = set(verify_expected_dirty_paths(manifest))
    to_stage = tuple(path for path in manifest.allowed_paths if path in dirty)
    if to_stage:
        _run_git(manifest.repo_path, 'add', '--', *to_stage)
    return to_stage


def commit_changes(manifest: PublicationManifest) -> str:
    staged = _run_git(manifest.repo_path, 'diff', '--cached', '--name-only').strip()
    head = _run_git(manifest.repo_path, 'rev-parse', 'HEAD').strip()
    if not staged:
        if head == manifest.base_sha:
            raise GitPublisherError('nothing staged and HEAD matches base_sha')
        return head
    _run_git(manifest.repo_path, 'commit', '-m', manifest.commit_message)
    return _run_git(manifest.repo_path, 'rev-parse', 'HEAD').strip()


def verify_branch_ancestry(manifest: PublicationManifest) -> None:
    merge_base = _run_git(
        manifest.repo_path,
        'merge-base',
        manifest.feature_branch,
        manifest.base_branch,
    ).strip()
    if merge_base != manifest.base_sha:
        raise GitPublisherError(
            f'{manifest.feature_branch} merge-base {merge_base!r} does not match '
            f'authorized base_sha {manifest.base_sha!r}'
        )


def push_branch(manifest: PublicationManifest) -> None:
    _run_git(
        manifest.repo_path,
        'push',
        'origin',
        f'{manifest.feature_branch}:{manifest.feature_branch}',
    )


def validate_pr_template(manifest: PublicationManifest) -> None:
    template_path = manifest.repo_path / '.github' / 'PULL_REQUEST_TEMPLATE.md'
    if template_path.exists():
        required_sections = [
            line.strip()
            for line in template_path.read_text(encoding='utf-8').splitlines()
            if line.startswith('## ')
        ]
        missing = [s for s in required_sections if s not in manifest.pr_body]
        if missing:
            raise GitPublisherError(f'pr_body missing required section(s): {missing}')
    if not manifest.evidence_links:
        raise GitPublisherError('pr_body must include at least one evidence link')
    missing_links = [
        link for link in manifest.evidence_links if link not in manifest.pr_body
    ]
    if missing_links:
        raise GitPublisherError(f'pr_body missing evidence link(s): {missing_links}')


def reconcile_or_create_pull_request(
    manifest: PublicationManifest, github: GitHubClient
) -> tuple[PullRequestRef, bool]:
    existing = github.find_pull_request(
        repo_path=manifest.repo_path, head_branch=manifest.feature_branch
    )
    if existing is not None:
        return existing, True
    validate_pr_template(manifest)
    created = github.create_pull_request(
        CreatePullRequestInput(
            repo_path=manifest.repo_path,
            base=manifest.base_branch,
            head=manifest.feature_branch,
            title=manifest.pr_title,
            body=manifest.pr_body,
            reviewers=manifest.reviewers,
        )
    )
    return created, False


def publish(manifest: PublicationManifest, github: GitHubClient) -> PublicationResult:
    _validate_manifest(manifest)
    checkout_feature_branch(manifest)

    existing = github.find_pull_request(
        repo_path=manifest.repo_path, head_branch=manifest.feature_branch
    )
    if existing is not None and existing.state == 'merged':
        return PublicationResult(
            head_sha=existing.head_sha,
            pull_request=existing,
            reused_existing_pr=True,
            already_merged=True,
        )

    stage_paths(manifest)
    head_sha = commit_changes(manifest)
    verify_branch_ancestry(manifest)
    push_branch(manifest)

    pull_request, reused = reconcile_or_create_pull_request(manifest, github)
    return PublicationResult(
        head_sha=head_sha,
        pull_request=pull_request,
        reused_existing_pr=reused,
        already_merged=False,
    )


@dataclass(frozen=True, slots=True)
class MergeRequest:
    repo_path: Path
    merge_strategy: str
    delete_branch_on_merge: bool
    expected_head_sha: str


def merge_pull_request(
    github: GitHubClient, pull_request: PullRequestRef, request: MergeRequest
) -> None:
    if pull_request.head_sha != request.expected_head_sha:
        raise GitPublisherError(
            f'refusing to merge: PR head {pull_request.head_sha!r} != '
            f'expected {request.expected_head_sha!r}'
        )
    github.merge_pull_request(
        repo_path=request.repo_path,
        number=pull_request.number,
        strategy=request.merge_strategy,
        delete_branch=request.delete_branch_on_merge,
    )


_GH_IN_PROGRESS_STATES = frozenset({'PENDING', 'QUEUED', 'IN_PROGRESS', 'EXPECTED'})
_GH_MERGE_STRATEGY_FLAGS = {
    'squash': '--squash',
    'merge': '--merge',
    'rebase': '--rebase',
}


class GhCliClient:
    def _gh(self, repo_path: Path, *args: str) -> str:
        resolved = shutil.which('gh')
        if resolved is None:
            raise GitCommandError(('gh',), -1, 'gh executable not found on PATH')
        argv = (resolved, *args)
        result = subprocess.run(  # noqa: S603
            argv,
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise GitCommandError(argv, result.returncode, result.stderr)
        return result.stdout

    def find_pull_request(
        self, *, repo_path: Path, head_branch: str
    ) -> PullRequestRef | None:
        try:
            output = self._gh(
                repo_path,
                'pr',
                'view',
                head_branch,
                '--json',
                'number,url,headRefOid,state',
            )
        except GitCommandError:
            return None
        data = json.loads(output)
        return PullRequestRef(
            number=data['number'],
            url=data['url'],
            head_sha=data['headRefOid'],
            state=data['state'].lower(),
        )

    def create_pull_request(self, request: CreatePullRequestInput) -> PullRequestRef:
        args = [
            'pr',
            'create',
            '--head',
            request.head,
            '--base',
            request.base,
            '--title',
            request.title,
            '--body',
            request.body,
        ]
        for reviewer in request.reviewers:
            args += ['--reviewer', reviewer]
        self._gh(request.repo_path, *args)
        created = self.find_pull_request(
            repo_path=request.repo_path, head_branch=request.head
        )
        if created is None:  # pragma: no cover
            raise GitCommandError(('gh', 'pr', 'create'), -1, 'PR not found after create')
        return created

    def list_check_runs(
        self, *, repo_path: Path, head_sha: str
    ) -> tuple[CheckRunObservation, ...]:
        output = self._gh(repo_path, 'pr', 'checks', '--json', 'name,state,link')
        observations = []
        for entry in json.loads(output):
            state = str(entry.get('state', '')).upper()
            if state in _GH_IN_PROGRESS_STATES:
                status, conclusion = 'in_progress', None
            else:
                status, conclusion = 'completed', state.lower()
            observations.append(
                CheckRunObservation(
                    name=entry['name'],
                    head_sha=head_sha,
                    status=status,
                    conclusion=conclusion,
                    url=entry.get('link'),
                )
            )
        return tuple(observations)

    def merge_pull_request(
        self,
        *,
        repo_path: Path,
        number: int,
        strategy: str,
        delete_branch: bool,
    ) -> None:
        args = ['pr', 'merge', str(number), _GH_MERGE_STRATEGY_FLAGS[strategy]]
        if delete_branch:
            args.append('--delete-branch')
        self._gh(repo_path, *args)

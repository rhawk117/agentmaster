"""Bounded git-publisher operations (SPEC.md §20.2, §23 Microtask 22).

The publisher receives an approved `PublicationManifest` -- repository, base
branch/SHA, feature branch, explicit paths, commit/PR text, merge policy --
and refuses anything that manifest does not authorize (§20.2: "It must refuse
to stage unexpected paths; rewrite history or force-push; ..."). Every git
mutation here takes no force/rewrite parameter at all, so there is no code
path that could be asked to force-push or delete a ref this module did not
itself create: `push_branch` always pushes a plain fast-forward update of
exactly `feature_branch`, and the only ref deletion (an already-merged
branch) is delegated to the injected `GitHubClient`, never performed locally.
`GitHubClient` is a `Protocol` so tests inject a fake instead of talking to
GitHub; `publish` reconciles an existing branch/PR/merge state on retry
instead of duplicating work.
"""

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
# A ref/branch argument starting with '-' could be parsed as a git flag
# instead of a name (classic argument injection); refuse it before it ever
# reaches a subprocess argv.
_UNSAFE_REF_RE = re.compile(r'^-')


class GitPublisherError(ValueError):
    """A publication manifest or requested operation violates a §20.2 refusal rule."""


class GitCommandError(RuntimeError):
    """A `git` subprocess invocation exited non-zero."""

    def __init__(self, args: Sequence[str], returncode: int, stderr: str) -> None:
        super().__init__(f'{" ".join(args)!r} exited {returncode}: {stderr.strip()}')
        self.returncode = returncode
        self.stderr = stderr


@dataclass(frozen=True, slots=True)
class PublicationManifest:
    """The approved publication manifest a git-publisher call receives (§20.2)."""

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
    """One pull request as reported by a `GitHubClient`."""

    number: int
    url: str
    head_sha: str
    state: str


@dataclass(frozen=True, slots=True)
class CreatePullRequestInput:
    """Everything a `GitHubClient.create_pull_request` call needs."""

    repo_path: Path
    base: str
    head: str
    title: str
    body: str
    reviewers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CheckRunObservation:
    """One observed check-run, as `GitHubClient.list_check_runs` reports it."""

    name: str
    head_sha: str
    status: str
    conclusion: str | None
    provider_check_id: str | None = None
    url: str | None = None


class GitHubClient(Protocol):
    """The GitHub operations a git-publisher call needs; fake this in tests."""

    def find_pull_request(
        self, *, repo_path: Path, head_branch: str
    ) -> PullRequestRef | None:
        """Return the open/merged/closed PR for `head_branch`, or `None`."""
        ...

    def create_pull_request(self, request: CreatePullRequestInput) -> PullRequestRef:
        """Open a new PR and return its reference."""
        ...

    def list_check_runs(
        self, *, repo_path: Path, head_sha: str
    ) -> tuple[CheckRunObservation, ...]:
        """Return every check-run GitHub currently reports for `head_sha`."""
        ...

    def merge_pull_request(
        self,
        *,
        repo_path: Path,
        number: int,
        strategy: str,
        delete_branch: bool,
    ) -> None:
        """Merge PR `number`. Never called with a force/admin-override option."""
        ...


@dataclass(frozen=True, slots=True)
class PublicationResult:
    """The outcome of one `publish` call: the pushed head and its PR."""

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
    result = subprocess.run(  # noqa: S603 -- argv list, no shell, git resolved via PATH
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
    """Return every path `git status --porcelain` reports as changed/untracked."""
    output = _run_git(repo_path, 'status', '--porcelain')
    paths: list[str] = []
    for line in output.splitlines():
        if not line:
            continue
        # porcelain format: "XY path" or "XY orig -> path" for renames.
        path = line[3:].split(' -> ')[-1].strip()
        paths.append(path)
    return tuple(paths)


def verify_expected_dirty_paths(manifest: PublicationManifest) -> tuple[str, ...]:
    """Return the repo's current dirty paths, refusing any outside the manifest.

    Raises
    ------
    GitPublisherError
        A path reported by `git status` is not in `manifest.allowed_paths` or
        `manifest.expected_dirty_paths` (§20.2: "refuse to stage unexpected
        paths").
    """
    permitted = set(manifest.allowed_paths) | set(manifest.expected_dirty_paths)
    dirty = _status_paths(manifest.repo_path)
    unexpected = [path for path in dirty if path not in permitted]
    if unexpected:
        raise GitPublisherError(
            f'unexpected dirty path(s), refusing to stage: {unexpected}'
        )
    return dirty


def checkout_feature_branch(manifest: PublicationManifest) -> None:
    """Create or check out `manifest.feature_branch`, idempotent for a retry."""
    existing = _run_git(
        manifest.repo_path, 'branch', '--list', manifest.feature_branch
    ).strip()
    if existing:
        _run_git(manifest.repo_path, 'checkout', manifest.feature_branch)
    else:
        _run_git(manifest.repo_path, 'checkout', '-b', manifest.feature_branch)


def stage_paths(manifest: PublicationManifest) -> tuple[str, ...]:
    """Stage exactly `manifest.allowed_paths`' dirty members; refuse anything else.

    Raises
    ------
    GitPublisherError
        `verify_expected_dirty_paths` rejects the repository's current state.
    """
    dirty = set(verify_expected_dirty_paths(manifest))
    to_stage = tuple(path for path in manifest.allowed_paths if path in dirty)
    if to_stage:
        _run_git(manifest.repo_path, 'add', '--', *to_stage)
    return to_stage


def commit_changes(manifest: PublicationManifest) -> str:
    """Commit staged changes and return the new HEAD SHA.

    If nothing is staged and HEAD already differs from `manifest.base_sha`,
    a prior attempt already committed -- this is a retry, not an error, and
    the existing HEAD SHA is returned unchanged.

    Raises
    ------
    GitPublisherError
        Nothing is staged and HEAD still matches `manifest.base_sha` (no
        work exists to commit).
    """
    staged = _run_git(manifest.repo_path, 'diff', '--cached', '--name-only').strip()
    head = _run_git(manifest.repo_path, 'rev-parse', 'HEAD').strip()
    if not staged:
        if head == manifest.base_sha:
            raise GitPublisherError('nothing staged and HEAD matches base_sha')
        return head
    _run_git(manifest.repo_path, 'commit', '-m', manifest.commit_message)
    return _run_git(manifest.repo_path, 'rev-parse', 'HEAD').strip()


def verify_branch_ancestry(manifest: PublicationManifest) -> None:
    """Refuse to push if the feature branch's history diverges from `base_sha`.

    Raises
    ------
    GitPublisherError
        `git merge-base` between `manifest.feature_branch` and `manifest.
        base_branch` is not exactly `manifest.base_sha` -- the branch carries
        commits this manifest did not authorize (§20.2: "feature branch and
        allowed commits").
    """
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
    """Push `manifest.feature_branch` to `origin`. Never force, never rewrites."""
    _run_git(
        manifest.repo_path,
        'push',
        'origin',
        f'{manifest.feature_branch}:{manifest.feature_branch}',
    )


def validate_pr_template(manifest: PublicationManifest) -> None:
    """Validate `manifest.pr_body` covers the repo's PR template and evidence links.

    Raises
    ------
    GitPublisherError
        A `## `-headed section from `.github/PULL_REQUEST_TEMPLATE.md` is
        missing from `pr_body`, or `evidence_links` is empty or one of its
        entries does not appear in `pr_body`.
    """
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
    """Return the existing PR for the feature branch, or validate and create one.

    Returns
    -------
    A `(pull_request, reused_existing)` pair.
    """
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
    """Stage, commit, push, and open (or reconcile) a PR for `manifest`.

    Idempotent for retry: an already-merged PR short-circuits without a new
    push or commit; an already-open PR for the feature branch is reused
    rather than duplicated.

    Raises
    ------
    GitPublisherError
        Any §20.2 refusal rule rejects the manifest or repository state.
    """
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
    """Everything a `merge_pull_request` call needs besides the client and PR."""

    repo_path: Path
    merge_strategy: str
    delete_branch_on_merge: bool
    expected_head_sha: str


def merge_pull_request(
    github: GitHubClient, pull_request: PullRequestRef, request: MergeRequest
) -> None:
    """Merge `pull_request`, refusing unless its head is exactly the expected SHA.

    This is defense-in-depth alongside `ledger.delivery_gate`'s merge gate:
    the publisher itself refuses "to merge a head different from the
    reviewed and green SHA" (§20.2) even if a caller skipped that gate.

    Raises
    ------
    GitPublisherError
        `pull_request.head_sha` does not equal `request.expected_head_sha`.
    """
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


# GitHub check-run states that are not yet a terminal completed result.
_GH_IN_PROGRESS_STATES = frozenset({'PENDING', 'QUEUED', 'IN_PROGRESS', 'EXPECTED'})
_GH_MERGE_STRATEGY_FLAGS = {
    'squash': '--squash',
    'merge': '--merge',
    'rebase': '--rebase',
}


class GhCliClient:
    """Production `GitHubClient` backed by the `gh` CLI.

    Never exercised against a real GitHub remote in this test suite -- every
    test injects a fake `GitHubClient` instead (SPEC.md §23 Microtask 22
    scope: "tests using local git fixtures/fake GitHub responses").
    """

    def _gh(self, repo_path: Path, *args: str) -> str:
        resolved = shutil.which('gh')
        if resolved is None:
            raise GitCommandError(('gh',), -1, 'gh executable not found on PATH')
        argv = (resolved, *args)
        result = subprocess.run(  # noqa: S603 -- argv list, no shell, gh resolved via PATH
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
        if created is None:  # pragma: no cover -- gh reported success but no PR found
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

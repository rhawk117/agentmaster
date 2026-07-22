"""Shared fixtures for the agentmaster test suite."""

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from installer.manifest import Manifest
from ledger.connection import connect as connect_ledger
from ledger.migrations import migrate as migrate_ledger

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable, Iterator, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent

# A fixed timestamp for ledger rows seeded by `seed_project_run_task`/`seed_memory`;
# tests that assert on `created_at`/`updated_at` compare against this constant.
LEDGER_SEED_CREATED_AT = '2026-07-20T00:00:00Z'

# Substrings identifying environment variables that must not leak from the
# developer/CI host into subprocess-driven tests (Claude, Copilot, Agentmaster
# home, ledger, compaction, debug, GitHub, and token variables).
_ENV_SCRUB_SUBSTRINGS = (
    'CLAUDE',
    'COPILOT',
    'AGENTMASTER',
    'LEDGER',
    'COMPACT',
    'DEBUG',
    'GITHUB',
    'GH_',
    'TOKEN',
)


def _scrubbed_base_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not any(needle in key.upper() for needle in _ENV_SCRUB_SUBSTRINGS)
    }


@pytest.fixture(scope='session')
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def repo_copy(tmp_path: Path) -> Path:
    """A disposable copy of the repository tree, sans VCS and caches."""
    dest = tmp_path / 'repo'
    shutil.copytree(
        REPO_ROOT,
        dest,
        ignore=shutil.ignore_patterns(
            '.git', '.venv', '__pycache__', '.superpowers', '.agentmaster'
        ),
    )
    return dest


@pytest.fixture(scope='session')
def statuses() -> Callable[[list[tuple[str, Path]]], list[str]]:
    def _statuses(entries: list[tuple[str, Path]]) -> list[str]:
        return [status for status, _ in entries]

    return _statuses


@pytest.fixture
def make_manifest() -> Callable[..., Manifest]:
    """Factory for fake Manifests; every field defaults to empty."""

    def _make(**overrides: object) -> Manifest:
        fields: dict = {
            'workers': (),
            'claude_skills': (),
            'copilot_coordinators': (),
            'claude_only_agents': (),
            'claude_hooks': (),
            'copilot_hooks': (),
            'claude_frontmatter': {},
            'copilot_frontmatter': {},
            'substitutions': {},
        }
        fields.update(overrides)
        return Manifest(**fields)

    return _make


@pytest.fixture
def run_cli() -> Callable[..., subprocess.CompletedProcess[str]]:
    def _run(
        args: list[str],
        cwd: Path,
        env_extra: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = _scrubbed_base_env()
        env.update(env_extra or {})
        return subprocess.run(  # noqa: S603
            [sys.executable, 'install.py', *args],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    return _run


@pytest.fixture
def run_hook(tmp_path: Path) -> Callable[..., subprocess.CompletedProcess[str]]:
    def _run(
        name: str,
        payload: object,
        env_extra: Mapping[str, str] | None = None,
        raw: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        stdin = raw if raw is not None else json.dumps(payload)
        env = _scrubbed_base_env()
        env.update(env_extra or {})
        return subprocess.run(  # noqa: S603
            [sys.executable, str(REPO_ROOT / 'hooks' / f'{name}.py')],
            input=stdin,
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env=env,
            timeout=30,
            check=False,
        )

    return _run


@pytest.fixture
def installed_hook() -> Callable[..., subprocess.CompletedProcess[str]]:
    """Invoke an INSTALLED hook file (not the source checkout's `hooks/`).

    Complements `run_hook`: tests asserting the runtime-descriptor-driven
    auto-drain (which resolves `runtime.json` relative to the hook's own
    installed location) must run the hook copy the installer actually wrote
    -- e.g. `<claude_home>/agentmaster/hooks/telemetry.py` -- with `cwd` set
    to the target workspace the payload's `cwd` field also names.
    """

    def _run(
        hook_path: Path,
        payload: object,
        cwd: Path,
        env_extra: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = _scrubbed_base_env()
        env.update(env_extra or {})
        return subprocess.run(  # noqa: S603
            [sys.executable, str(hook_path)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=str(cwd),
            env=env,
            timeout=30,
            check=False,
        )

    return _run


@dataclass(frozen=True, slots=True)
class SeededRun:
    """Canonical ids for one seeded PROJECT + USER_SESSION + RUN (+ optional TASK)."""

    project_id: str = 'project-1'
    user_session_id: str = 'user-session-1'
    run_id: str = 'run-1'
    task_id: str | None = 'task-1'
    task_title: str = 'retry backoff'


def seed_project_run_task(
    connection: sqlite3.Connection, seed: SeededRun | None = None
) -> SeededRun:
    """Insert one PROJECT/USER_SESSION/RUN row, and a TASK row unless `seed.task_id`
    is `None`.
    """
    if seed is None:
        seed = SeededRun()
    connection.execute(
        'INSERT INTO PROJECT (id, canonical_root, fingerprint, created_at, last_seen_at) '
        'VALUES (?, ?, ?, ?, ?)',
        (
            seed.project_id,
            '/repo',
            f'fp-{seed.project_id}',
            LEDGER_SEED_CREATED_AT,
            LEDGER_SEED_CREATED_AT,
        ),
    )
    connection.execute(
        'INSERT INTO USER_SESSION (user_session_id, harness_session_id, created_at) '
        'VALUES (?, ?, ?)',
        (seed.user_session_id, 'harness-1', LEDGER_SEED_CREATED_AT),
    )
    connection.execute(
        'INSERT INTO RUN '
        '(id, project_id, user_session_id, delivery_mode, state, started_at) '
        "VALUES (?, ?, ?, 'local', 'Planned', ?)",
        (seed.run_id, seed.project_id, seed.user_session_id, LEDGER_SEED_CREATED_AT),
    )
    if seed.task_id is not None:
        connection.execute(
            'INSERT INTO TASK (id, run_id, title, state, sequence_no) '
            "VALUES (?, ?, ?, 'ready', 1)",
            (seed.task_id, seed.run_id, seed.task_title),
        )
    connection.commit()
    return seed


@dataclass(frozen=True, slots=True)
class SeededMemory:
    """Canonical fields for one seeded, project-scoped MEMORY row."""

    memory_id: str
    project_id: str = 'project-1'
    state: str = 'Active'
    title: str = 'title'
    content: str = 'content'


def seed_memory(connection: sqlite3.Connection, seed: SeededMemory) -> SeededMemory:
    """Insert one MEMORY row and its project-scoped MEMORY_SCOPE row."""
    connection.execute(
        'INSERT INTO MEMORY '
        '(id, origin_project_id, state, memory_kind, title, content, created_at, '
        'updated_at) '
        "VALUES (?, ?, ?, 'lesson', ?, ?, ?, ?)",
        (
            seed.memory_id,
            seed.project_id,
            seed.state,
            seed.title,
            seed.content,
            LEDGER_SEED_CREATED_AT,
            LEDGER_SEED_CREATED_AT,
        ),
    )
    connection.execute(
        'INSERT INTO MEMORY_SCOPE (memory_id, scope_kind, project_id, created_at) '
        "VALUES (?, 'project', ?, ?)",
        (seed.memory_id, seed.project_id, LEDGER_SEED_CREATED_AT),
    )
    connection.commit()
    return seed


@pytest.fixture
def ledger_connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A freshly migrated, unseeded ledger connection at the current schema version.

    The single stable, side-effect-free replacement for the ad hoc
    `connect(tmp_path / 'ledger.sqlite3')` + `migrate(...)` pairs previously
    copy-pasted (with subtly different seeding baked in) across the ledger
    test modules.
    """
    connection = connect_ledger(tmp_path / 'ledger.sqlite3')
    migrate_ledger(connection)
    yield connection
    connection.close()

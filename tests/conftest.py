"""Shared fixtures for the agentmaster test suite."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from installer.manifest import Manifest

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent

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

"""Shared fixtures for the agentmaster test suite."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from installer.manifest import Manifest

REPO_ROOT = Path(__file__).resolve().parent.parent


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
def statuses():
    def _statuses(entries) -> list[str]:
        return [status for status, _ in entries]

    return _statuses


@pytest.fixture
def make_manifest():
    """Factory for fake Manifests; every field defaults to empty."""

    def _make(**overrides) -> Manifest:
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
def run_cli():
    def _run(args, cwd, env_extra=None):
        env = dict(os.environ)
        env.update(env_extra or {})
        return subprocess.run(  # noqa: S603
            [sys.executable, 'install.py', *args],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    return _run


@pytest.fixture
def run_hook(tmp_path: Path):
    def _run(name, payload, env=None, raw=None):
        stdin = raw if raw is not None else json.dumps(payload)
        return subprocess.run(  # noqa: S603
            [sys.executable, str(REPO_ROOT / 'hooks' / f'{name}.py')],
            input=stdin,
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env=env,
            check=False,
        )

    return _run

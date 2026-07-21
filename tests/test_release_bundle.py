"""Tests for the release archive's tested source of truth (SPEC.md microtask 24)."""

import os
import subprocess
import sys
import zipfile

import pytest

from scripts.release_bundle import (
    REPO_ROOT,
    RUNTIME_PATHS,
    build_archive,
    write_checksums,
)

# Same substrings tests/conftest.py's _scrubbed_base_env uses, duplicated here
# so this module has no import-time dependency on conftest internals.
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


def _scrubbed_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not any(needle in key.upper() for needle in _ENV_SCRUB_SUBSTRINGS)
    }


def test_runtime_paths_exist_and_are_tracked():
    for entry in RUNTIME_PATHS:
        path = REPO_ROOT / entry
        assert path.exists(), f'{entry} does not exist'
        tracked = subprocess.run(  # noqa: S603
            ['git', 'ls-files', '--error-unmatch', entry],  # noqa: S607
            cwd=REPO_ROOT,
            capture_output=True,
            timeout=10,
            check=False,
        )
        assert tracked.returncode == 0, f'{entry} is not git-tracked'


def test_runtime_paths_include_the_runtime_modules():
    # Regression guard: an earlier release.yml archived the installer and
    # skills but omitted the `agentmaster` CLI package and the `ledger`
    # module it depends on, so the extracted bundle couldn't run
    # `python -m agentmaster ledger doctor`.
    assert 'agentmaster' in RUNTIME_PATHS
    assert 'ledger' in RUNTIME_PATHS


def test_runtime_paths_exclude_tests_and_dev_only_files():
    assert 'tests' not in RUNTIME_PATHS
    assert '.github' not in RUNTIME_PATHS
    assert 'evals' not in RUNTIME_PATHS


@pytest.mark.subprocess
def test_archive_extracts_and_smoke_tests_clean(tmp_path):
    archive_path = tmp_path / 'agentmaster-test.zip'
    checksums_path = tmp_path / 'SHA256SUMS'

    build_archive(archive_path, ref='HEAD')
    write_checksums([archive_path], checksums_path)

    assert archive_path.is_file()
    checksum_line = checksums_path.read_text(encoding='utf-8').strip()
    digest, name = checksum_line.split('  ', 1)
    assert len(digest) == 64
    assert name == archive_path.name

    extracted = tmp_path / 'extracted'
    with zipfile.ZipFile(archive_path) as zf:
        names = zf.namelist()
        zf.extractall(extracted)

    assert not any(name.startswith('tests/') for name in names)
    assert any(name.startswith('agentmaster/') for name in names)
    assert any(name.startswith('ledger/') for name in names)

    env = _scrubbed_env()

    install_help = subprocess.run(
        [sys.executable, 'install.py', '--help'],
        cwd=extracted,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )
    assert install_help.returncode == 0, install_help.stderr

    doctor_help = subprocess.run(
        [sys.executable, '-m', 'agentmaster', 'ledger', 'doctor', '--help'],
        cwd=extracted,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )
    assert doctor_help.returncode == 0, doctor_help.stderr

    ledger_path = tmp_path / 'smoke-ledger.sqlite3'
    init_result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            '-m',
            'agentmaster',
            'ledger',
            'init',
            '--path',
            str(ledger_path),
        ],
        cwd=extracted,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )
    assert init_result.returncode == 0, init_result.stderr
    assert ledger_path.is_file()

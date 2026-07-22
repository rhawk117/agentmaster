"""Single source of truth for what ships in a release archive (SPEC.md microtask 24).

Both `release.yml` and tests/test_release_bundle.py import RUNTIME_PATHS, so
the archive's membership and its regression test can never drift apart.
"""

import argparse
import hashlib
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Every entry is git-tracked at the repo root. `git archive` walks each path
# recursively and only ever includes tracked content, so it can't leak
# untracked caches, local ledgers, artifacts, WAL/SHM files, backups,
# worktrees, or session data even without an explicit exclude list.
RUNTIME_PATHS = (
    'install.py',
    'installer',
    'agentmaster',
    'ledger',
    'shared',
    'agents',
    'copilot',
    'skills',
    'hooks',
    'criteria',
    'scripts/telemetry_report.py',
    'scripts/release_bundle.py',
    'README.md',
    'LICENSE',
    'pyproject.toml',
)


def build_archive(dest: Path, ref: str = 'HEAD') -> Path:
    """Write a zip of RUNTIME_PATHS at `ref` to `dest`; return `dest`."""
    subprocess.run(  # noqa: S603
        ['git', 'archive', '--format=zip', f'--output={dest}', ref, '--', *RUNTIME_PATHS],  # noqa: S607
        cwd=REPO_ROOT,
        check=True,
        timeout=60,
    )
    return dest


def write_checksums(paths: list[Path], dest: Path) -> Path:
    """Write a `sha256sum --check`-compatible SHA256SUMS file for `paths`."""
    lines = [
        f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n'
        for path in paths
    ]
    dest.write_text(''.join(lines), encoding='utf-8')
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Build the agentmaster release bundle.')
    parser.add_argument('archive', type=Path, help='output zip path')
    parser.add_argument('--ref', default='HEAD', help='git tree-ish to archive')
    parser.add_argument(
        '--checksums', type=Path, default=None, help='SHA256SUMS output path'
    )
    args = parser.parse_args(argv)
    archive = build_archive(args.archive, ref=args.ref)
    if args.checksums is not None:
        write_checksums([archive], args.checksums)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

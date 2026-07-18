"""Summarize agentmaster telemetry.

Reads `.agentmaster/telemetry.md` (or the path given as the first argument),
whose lines look like `hook,<agent>,,<tokens>,<duration_ms>` with blank fields
allowed, and prints per-agent invocation counts, token totals, and wall-clock
totals. Exits 1 when the telemetry file does not exist. With `--prune`, trims
old telemetry lines, compaction snapshots, and stale session-start markers.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path


def summarize(path: Path) -> str:
    totals: dict[str, list[int]] = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        parts = line.split(',')
        if len(parts) < 5 or parts[0] != 'hook':
            continue
        runs = totals.setdefault(parts[1] or 'unknown', [0, 0, 0])
        runs[0] += 1
        runs[1] += int(parts[3]) if parts[3].isdigit() else 0
        runs[2] += int(parts[4]) if parts[4].isdigit() else 0
    if not totals:
        return 'no telemetry lines found'
    width = max(len(agent) for agent in totals)
    header = f'{"agent":<{width}}  runs  tokens  wall-clock'
    rows = [
        f'{agent:<{width}}  {runs:>4}  {tokens:>6}  {ms / 1000:>8.1f}s'
        for agent, (runs, tokens, ms) in sorted(totals.items())
    ]
    return '\n'.join([header, *rows])


def _prune_telemetry(am_dir: Path, keep_lines: int, *, dry_run: bool) -> list[str]:
    telemetry = am_dir / 'telemetry.md'
    if not telemetry.is_file():
        return []
    lines = telemetry.read_text(encoding='utf-8').splitlines(keepends=True)
    excess = len(lines) - keep_lines
    if excess <= 0:
        return []
    if not dry_run:
        tmp = telemetry.with_name('telemetry.md.tmp')
        tmp.write_text(''.join(lines[-keep_lines:]), encoding='utf-8')
        tmp.replace(telemetry)
    return [f'telemetry.md: drop {excess} oldest of {len(lines)} lines']


def _prune_snapshots(am_dir: Path, keep_snapshots: int, *, dry_run: bool) -> list[str]:
    snapshots = am_dir / 'compaction-snapshots'
    if not snapshots.is_dir():
        return []
    dirs = sorted(p for p in snapshots.iterdir() if p.is_dir())
    stale = dirs[:-keep_snapshots] if keep_snapshots > 0 else dirs
    if not dry_run:
        for path in stale:
            shutil.rmtree(path)
    return [f'compaction-snapshots/{path.name}: remove' for path in stale]


def _prune_starts(am_dir: Path, *, dry_run: bool) -> list[str]:
    starts = am_dir / '.starts'
    if not starts.is_dir():
        return []
    cutoff = time.time() - 24 * 60 * 60
    stale = sorted(
        p for p in starts.iterdir() if p.is_file() and p.stat().st_mtime < cutoff
    )
    if not dry_run:
        for path in stale:
            path.unlink()
    return [f'.starts/{path.name}: remove stale entry' for path in stale]


def prune(
    am_dir: Path, *, keep_lines: int, keep_snapshots: int, dry_run: bool
) -> list[str]:
    """Prune telemetry artifacts under `am_dir`; return the actions taken."""
    return [
        *_prune_telemetry(am_dir, keep_lines, dry_run=dry_run),
        *_prune_snapshots(am_dir, keep_snapshots, dry_run=dry_run),
        *_prune_starts(am_dir, dry_run=dry_run),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Report or prune agentmaster telemetry.')
    parser.add_argument(
        'path',
        nargs='?',
        type=Path,
        default=Path('.agentmaster') / 'telemetry.md',
        help='telemetry file (default: .agentmaster/telemetry.md)',
    )
    parser.add_argument(
        '--prune', action='store_true', help='prune old telemetry artifacts'
    )
    parser.add_argument('--keep-lines', type=int, default=500)
    parser.add_argument('--keep-snapshots', type=int, default=5)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    if args.prune:
        actions = prune(
            args.path.parent,
            keep_lines=args.keep_lines,
            keep_snapshots=args.keep_snapshots,
            dry_run=args.dry_run,
        )
        if not actions:
            print('nothing to prune')
            return 0
        prefix = 'would ' if args.dry_run else ''
        for action in actions:
            print(prefix + action)
        return 0
    if not args.path.is_file():
        print(
            f'no telemetry file at {args.path} - run agentmaster first', file=sys.stderr
        )
        return 1
    print(summarize(args.path))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

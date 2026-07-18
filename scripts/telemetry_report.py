"""Summarize agentmaster telemetry.

Reads `.agentmaster/telemetry.md` (or the path given as the first argument),
whose lines look like `hook,<agent>,,<tokens>,<duration_ms>` with blank fields
allowed, and prints per-agent invocation counts, token totals, and wall-clock
totals. Exits 1 when the telemetry file does not exist.
"""

from __future__ import annotations

import sys
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


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0]) if args else Path('.agentmaster') / 'telemetry.md'
    if not path.is_file():
        print(f'no telemetry file at {path} - run agentmaster first', file=sys.stderr)
        return 1
    print(summarize(path))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

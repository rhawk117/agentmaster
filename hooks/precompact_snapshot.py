"""PreCompact -> snapshot .agentmaster/ so ledgers of record survive with history."""

import shutil
import tempfile
import time
from pathlib import Path

import hooklib


def _new_snapshot_dir(am: Path) -> Path:
    """Create and return a unique snapshot directory; never collides with a sibling.

    A timestamp prefix keeps directories sortable; `mkdtemp` guarantees the
    directory itself is created atomically, so same-second or same-process
    calls never merge or overwrite one another.
    """
    root = am / 'compaction-snapshots'
    root.mkdir(parents=True, exist_ok=True)
    ts = time.strftime('%Y%m%d-%H%M%S')
    return Path(tempfile.mkdtemp(prefix=f'{ts}-', dir=root))


def main() -> int:
    payload = hooklib.read_payload()
    hooklib.debug_dump(payload)
    am = hooklib.workspace(payload) / '.agentmaster'
    if am.is_dir():
        dst = _new_snapshot_dir(am)
        for p in am.iterdir():
            if p.name in ('compaction-snapshots', '.starts'):
                continue
            copy = shutil.copytree if p.is_dir() else shutil.copy2
            copy(p, dst / p.name)
        ctx = hooklib.compaction_context(payload)
        hooklib.append_telemetry(payload, f'precompact:{ctx.agent_type}', ctx.token_count)
        hooklib.spool_event(
            payload,
            {
                'kind': 'compaction',
                'cwd': str(hooklib.workspace(payload)),
                'agent_type': ctx.agent_type,
                'trigger': ctx.trigger,
                'token_count': int(ctx.token_count)
                if ctx.token_count.isdigit()
                else None,
                'snapshot_dir': str(dst),
            },
        )
        hooklib.auto_drain(payload)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

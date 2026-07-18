"""PreCompact -> snapshot .agentmaster/ so ledgers of record survive with history."""

import shutil
import time

import hooklib


def main() -> int:
    payload = hooklib.read_payload()
    am = hooklib.workspace(payload) / '.agentmaster'
    if am.is_dir():
        ts = time.strftime('%Y%m%d-%H%M%S')
        dst = am / 'compaction-snapshots' / ts
        dst.mkdir(parents=True, exist_ok=True)
        for p in am.iterdir():
            if p.name in ('compaction-snapshots', '.starts'):
                continue
            copy = shutil.copytree if p.is_dir() else shutil.copy2
            copy(p, dst / p.name)
        hooklib.append_telemetry(payload, 'precompact')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

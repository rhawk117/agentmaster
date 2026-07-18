"""SessionStart -> inject a re-hydration pointer when agentmaster artifacts exist."""

import hooklib


def main() -> int:
    payload = hooklib.read_payload()
    am = hooklib.workspace(payload) / '.agentmaster'
    if am.is_dir():
        files = sorted(p.name for p in am.iterdir() if p.is_file())
        if files:
            print(
                'agentmaster artifacts present in .agentmaster/ ({}). '
                'The ledger of record is ledger.md (review-ledger.md for reviews); '
                're-hydrate evidence from these files rather than trusting compacted '
                'memory of them.'.format(', '.join(files[:8]))
            )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

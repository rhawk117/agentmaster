import hooklib


def main() -> int:
    payload = hooklib.read_payload()
    root = hooklib.workspace(payload)
    sdir = hooklib.session_dir(payload)
    hooklib.auto_drain(payload)
    print(
        f'agentmaster session workspace: {sdir.relative_to(root)}/ - write '
        '.phase, .starts/, and telemetry.md here this session; '
        '.agentmaster/.phase is read as a legacy fallback.'
    )
    am = root / '.agentmaster'
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

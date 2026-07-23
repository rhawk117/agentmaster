import os
import sys

import hooklib


def main() -> int:
    hooklib.read_payload()
    model = os.environ.get('CLAUDE_CODE_SUBAGENT_MODEL')
    if not model:
        return 0
    sys.stderr.write(
        f"agentmaster: CLAUDE_CODE_SUBAGENT_MODEL='{model}' is exported and silently "
        "overrides every worker's model pin, defeating the haiku/sonnet tiering. Ask "
        'the user to unset it, then retry the dispatch.\n'
    )
    return 2


if __name__ == '__main__':
    raise SystemExit(main())

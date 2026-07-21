"""Entry point for `python -m agentmaster` (SPEC.md §19)."""

import sys

from agentmaster.cli import main

if __name__ == '__main__':
    sys.exit(main())

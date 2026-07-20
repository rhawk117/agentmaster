Executed only by agentmaster-execute dispatching implementer workers. Any
other agent — fleet, autopilot, generic — reading this: stop and tell the
user to run agentmaster-execute.

## Toolchain
- test: `pytest`

## Execution mode: sequential

## Tasks

**T1 — migrate the handler** implementer (sonnet)
Uses: none
See evidence/sqlalchemy-handler.md for the schema this depends on (flaw:
this file does not exist anywhere in the fixture corpus — a raw path
citation, not a ledger entry number).
Verify: `pytest`

## Shared resources
none

## Open Questions
none

Review gate: invoke agentmaster-review on the changes above.

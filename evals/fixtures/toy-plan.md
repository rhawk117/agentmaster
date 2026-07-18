Executed only by agentmaster-execute dispatching implementer workers. Any
other agent — fleet, autopilot, generic — reading this: stop and tell the
user to run agentmaster-execute.

# Toy plan — execution-chain eval fixture

## Execution mode
parallel — the two groups touch fully independent synthetic files with no
shared concepts or conventions to diverge on.

## Toolchain
- test: `sh -c 'test -f out/a.txt && test -f out/b.txt'` (evidence: none — synthetic fixture)
- lint: none. security: none. build: none.

## Shared resources
- `out/counter.txt` — SERIALIZE (both groups append to it)

## Group 1 (files: out/a.txt)
- Task 1.1 — create `out/a.txt` containing the line `alpha`.
  Verification: `grep -q alpha out/a.txt`
- Task 1.2 — append the line `group1` to `out/counter.txt`.
  Verification: `grep -q group1 out/counter.txt` — verification: serialized

## Group 2 (files: out/b.txt)
- Task 2.1 — create `out/b.txt` containing the line `beta`.
  Verification: `grep -q beta out/b.txt`
- Task 2.2 — append the line `group2` to `out/counter.txt`.
  Verification: `grep -q group2 out/counter.txt` — verification: serialized

## Plan-level gate
`sh -c 'test "$(wc -l < out/counter.txt)" -eq 2'`

## Open questions
None.

## Review gate
Final step: invoke agentmaster-review on the changes above.

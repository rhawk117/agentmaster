Orchestration calls — every execute run persists its RUN/TASK lifecycle
through `agentmaster run`/`task`/`dispatch`, never through prose bookkeeping
alone:

- `agentmaster run start --user-session-id <harness-session-id> --project-root
  <root> [--plan-id --base-sha --delivery-mode]` at Phase 1, before any
  dispatch. It reuses this session's existing open RUN if one exists
  (idempotent resume, never a second RUN) and atomically writes the RUN id
  to the session's `.run_id` marker so ledger ingestion attaches to the same
  RUN.
- `agentmaster run preflight --run-id <id> --check NAME:true|false[:DETAIL]`
  once per `PREFLIGHT_CATEGORIES` entry, persisting `Executing` or `Blocked`
  before Phase 2 dispatch begins.
- `agentmaster task register --run-id <id> --title --sequence-no
  [--depends-on TASK_ID:KIND]` once per plan task, in plan order, so the
  task graph and its dependencies are durable before any lease is acquired.
- `agentmaster dispatch acquire --task-id <id> --lease-agent-session-id <id>`
  immediately before dispatching an implementer for that task, and
  `agentmaster dispatch release --task-id <id> --to-state <state>`
  immediately after it returns (`review-required`, `blocked`, `failed`, or
  `complete`).
- `agentmaster task record-evidence --task-id --run-id --project-id
  --artifact-root --evidence-kind --exit-code [--commit-sha]` for every
  verification command a task's report claims passed.
- `agentmaster run transition --run-id <id> --to-state <state>` to move the
  RUN into `Verifying`, `FixesRequired`, `DeliveryPending`/review states,
  `RetrospectivePending`, `Complete`, or `Failed` as each gate resolves.
- `agentmaster run recover --run-id <id>` before resuming an interrupted run,
  releasing any stale task lease and recording the recovery decision, never
  re-dispatching a task whose lease recovery did not release.

Every one of these commands validates current state and fails closed
(non-zero exit, JSON `{"error": ...}`) on an illegal transition or unmet
precondition — the prompt is never the source of truth for RUN/TASK state.

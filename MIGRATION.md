# Migrating from v1 to v2

v1 ran three Claude Code skills (`agentmaster-plan`, `agentmaster-execute`,
`agentmaster-review`) with a single `--model` flag and append-only markdown
ledgers (`.agentmaster/ledger.md`, `.agentmaster/telemetry.md`). v2 keeps the
same three-phase pipeline (plus the new `agentmaster-retro` skill) but
replaces the markdown ledger with a local SQLite ledger and gives every
runtime role its own model/effort. Nothing about the plan/execute/review
skill workflow itself changes; the sections below cover what an existing v1
install needs to know before upgrading.

## `--model` is gone

v1's single `--model` flag has been replaced by one model (and, for Claude,
one effort) flag per role:

| v1 | v2 |
| --- | --- |
| `--model` (all roles) | `--claude-model` / `--copilot-model` (coordinator only) |
| — | `--claude-orchestrator-model` + `--claude-orchestrator-effort` |
| — | `--claude-implementer-model` + `--claude-implementer-effort` |
| — | `--claude-review-model` + `--claude-review-effort` |
| — | `--copilot-implementer-model` (Copilot has no orchestrator/reviewer role) |

Effort is one of `low|medium|high|xhigh|max`. An explicit flag always wins;
otherwise a TTY, non-`--no-input` session prompts per role; otherwise the
recommended default in `installer/config.py` (`DEFAULT_ROLE_MODEL` /
`DEFAULT_ROLE_EFFORT`) applies silently. Passing a `--claude-*` flag without
`--target claude` (or `all`), or a `--copilot-*` flag without `--target
copilot`, is rejected.

## Config precedence

Installer settings resolve **CLI flag > `--config` TOML file > built-in
default**. A `--config path/to/config.toml` document is a versioned
(`schema_version = 1`) table with `[paths]`, `[orchestration]`,
`[agents.claude.<role>]`, and `[ledger]` sections; unrecognized keys survive
a read/modify/write untouched. The installer also writes its own managed
copy to `<agentmaster-home>/config.toml` (default
`~/.agentmaster/config.toml`) reflecting whatever was resolved, so a rerun
without `--config` still shows the previous install's choices.

## The ledger: SQLite, not markdown

The v1 markdown ledgers are replaced by a single SQLite database, enabled by
default: `~/.agentmaster/ledger.sqlite3` (override with `--ledger-path`;
`--no-ledger` disables it — the two flags are mutually exclusive). An
artifact store sits alongside it (`--artifact-dir`, default
`<agentmaster-home>/artifacts`).

- **Local-filesystem constraint.** The ledger is supported only on a local
  filesystem. WAL journaling (better concurrent reader/writer throughput) is
  only selected when the runtime SQLite version carries the WAL-reset fix
  *and* the path is local; otherwise the ledger falls back to `DELETE`
  journaling and records why. `agentmaster ledger doctor` reports the active
  `journal_mode` and, when it differs from WAL, the recorded reason.
- **Single migration.** Pre-v2.0.0, all schema changes live in one
  migration, `ledger/migrations/0001_initial/upgrade.sql`; the chain only
  grows once v2.0.0 ships, so every existing v2-track ledger is already on
  schema version 1 after `agentmaster ledger migrate` (also run
  automatically by `ledger init`).
- **Backup/restore.** `agentmaster ledger backup --path <ledger> --destination
  <file>` checkpoints WAL into the main file and writes a consistent copy via
  SQLite's online backup API — safe to run against a live ledger. There is no
  separate restore verb: a backup is a complete, ordinary SQLite file, so
  restoring means copying it back over the ledger path (with the ledger
  otherwise idle) or pointing `--ledger-path` at it directly.
- **Privacy and retention.** Raw command/tool output and hook payloads are
  redacted before anything touches disk (`ledger/redaction.py`): known
  secret-shaped strings (API keys, bearer tokens, cloud credentials),
  filesystem paths outside an explicit allow-list, and env values under
  allow-listed names are masked before persistence, hashing, or artifact
  storage — never after. Raw capture defaults to `failures` (only failing
  commands keep captured output) and redaction defaults to `standard`;
  neither is currently user-configurable beyond the `[ledger]` TOML table's
  `raw_output` / `redaction` keys. Nothing prunes ledger rows automatically;
  retention is an explicit choice you make with your own SQLite tooling
  against the backup file.
- **Recovery.** `agentmaster ledger doctor --path <ledger> --json` reports
  schema version, journal mode (and fallback reason), integrity-check result,
  and pending-migration count without mutating anything — run it first after
  any interruption. A nonzero exit means the ledger is missing, failed
  integrity check, or reports a schema version newer than this build
  understands (never guessed at).

## Session-scoped workspaces

Repo-local session state now lives under `.agentmaster/sessions/<harness-session-id>/`
(telemetry, `.phase` marker, compaction snapshots) instead of directly under
`.agentmaster/`, so two sessions working the same checkout never clobber each
other's history. `harness_session_id` is also the `session_id` field on every
hook payload the ledger ingests (SPEC.md §17.1), so ledger rows and on-disk
session state correlate by the same id.

## Non-destructive v1 artifact import

`agentmaster migrate legacy-files` imports pre-v2 telemetry into the ledger
without touching the source files:

```bash
python -m agentmaster migrate legacy-files \
  --path ~/.agentmaster/ledger.sqlite3 \
  --workspace . \
  --dry-run          # preview counts; omit to apply
```

It discovers every legacy `telemetry.md` — both the pre-session-scoping root
file and any `.agentmaster/sessions/<id>/telemetry.md` — and imports each
`phase,agent,model,tokens,duration_ms` row as a `MODEL_CALL` under a
dedicated legacy `AGENT_SESSION`/`RUN`, one per source file. Import is
idempotent (rows are keyed by a content digest, so re-running never
duplicates them), original files are never modified or deleted, and each
imported file is registered as a redacted, content-addressed artifact for
provenance. Malformed or ambiguous rows are reported, not silently coerced.

## Feedback capture

`agentmaster ledger record-feedback` writes a `FEEDBACK` row (rating -1/0/1,
optional task/memory reference and comment) tied to a run and user session.
`agentmaster-retro`'s retrospective run attaches any feedback recorded since
the run started and can turn it into a memory-candidate proposal
(`agentmaster retro propose`) — the v1 pipeline had no equivalent capture
path.

## Delivery modes and the review gate

`--delivery-mode local|commit|pull-request|merge` (default `local`) sets how
far a run is allowed to publish its own changes; `local` never leaves the
working tree. `pull-request` and `merge` runs go through
`agentmaster delivery prepare-pr` → `watch-ci` → `review-gate` →
`merge-gate`, backed by `DELIVERY_ATTEMPT`/`CI_CHECK` ledger rows — a merge
only proceeds once CI is green for the exact head SHA the delivery attempt
recorded, closing the "review approved a different commit than what merged"
gap.

## Budgets

Per-run/per-task budgets (tokens, cost, wall-clock duration, parallelism,
context-pack tokens) are enforced at dispatch time by `ledger/budget_policy.py`
against whatever the orchestrator recorded on the run — there is no
installer flag for them. The budget-conscious lever available today is model
and effort selection per role (see the example below); a hard-budget stop is
a dispatch decision, not a change to a task's acceptance criteria.

## Rollback

Every install writes into a fresh `agentmaster-backup-<timestamp>/` under
the config home before overwriting anything. If a batch write fails partway
through, the installer rolls back everything it touched in that batch, most
recent first, restoring prior files from that backup and deleting anything
it had newly created; if rollback itself cannot fully restore, it reports
exactly which destinations are still unrestored rather than claiming
success. `python install.py uninstall --target all` reverses an install the
same way, including stripping merged hook entries out of `settings.json`
without touching hooks you already had.

## Worked examples

Default install (both platforms, ledger and local delivery on):

```bash
python install.py install
```

Budget-oriented (cheaper implementer, no opus reviewer elevation):

```bash
python install.py install --target claude \
  --claude-implementer-model sonnet --claude-implementer-effort low \
  --claude-review-model sonnet --claude-review-effort medium
```

No ledger:

```bash
python install.py install --no-ledger
```

50% compaction override (Claude only, recommended for long runs):

```bash
python install.py install --auto-compact-percent 50
```

Project memory query:

```bash
python -m agentmaster memory search --path ~/.agentmaster/ledger.sqlite3 \
  --project-id <project-id> --run-id <run-id> --query "review gate"
```

Retrospective over a completed run:

```bash
python -m agentmaster retro run --path ~/.agentmaster/ledger.sqlite3 \
  --run-id <run-id>
```

PR delivery:

```bash
python install.py install --delivery-mode pull-request
python -m agentmaster delivery prepare-pr --path ~/.agentmaster/ledger.sqlite3 \
  --run-id <run-id> --repo . --base-branch main --base-sha <sha> \
  --feature-branch <branch> --allowed-path <path> \
  --commit-message "..." --pr-title "..." --pr-body "..."
```

Recovery after an interrupted run:

```bash
python -m agentmaster ledger doctor --path ~/.agentmaster/ledger.sqlite3 --json
python -m agentmaster ledger backup --path ~/.agentmaster/ledger.sqlite3 \
  --destination ~/.agentmaster/ledger-backup.sqlite3
```

## Known limitations

- Provider-reported usage may be unavailable; when it is, monetary cost
  falls back to whatever pricing provenance the caller supplied.
- Embeddings are not included — memory search is not vector search.
- Implementer scouts are off by default.

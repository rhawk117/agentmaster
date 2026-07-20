Agentmaster v2.0.0 Control Plane, Ledger, Installer Modernization, and Release Specification

1. Purpose

This specification replaces the earlier v1.2.0 installer plan. It defines amajor Agentmaster release that modernizes installation and configuration whileturning the coordinator into an active, evidence-driven control plane.

The release must deliver four connected capabilities:

A safe Python 3.14 installer with configurable agent models and effort,explicit Claude auto-compaction, transactional settings, and clear UX.

Deterministic orchestration from plan through implementation, delivery, CI,independent review, merge, and retrospective.

A project-aware SQLite ledger for execution history, token accounting,evidence, memories, retrospectives, procedures, and delivery state.

A guarded recursive-improvement loop that evaluates experience and proposesbetter memories and procedures without silently rewriting Agentmaster.

This specification is written for an implementation agent. Execute it as asequence of small, sequential pull requests. Every task branch starts from thelatest develop; every logical commit is pushed immediately; every PR musthave green CI and an independent agentmaster-review verdict of GOOD for theexact head commit before merge.

Repository: rhawk117/agentmaster

Audited baseline on 2026-07-20:

Branch: develop

Commit: e19156c73d8d5611bc4cc111f4593e7e305aa620

Version: 1.1.1

Runtime: Python 3.14+

Runtime dependencies: none

Baseline quality: Ruff, bashate, ty, compileall, generated parity, and all 102tests pass

agentmaster-execute is currently a mechanical dispatcher; review invocationis prompt-level guidance rather than a persisted, enforceable state transition

Refresh develop before beginning. If it has advanced, the newest remote treeis authoritative. Record material drift in the first affected PR and reconcilethis specification without weakening its safety or acceptance contracts.

2. Release classification and compatibility

This is a major release: v2.0.0, unless another major release is publishedfirst. The earlier proposed v1.2.0 is superseded by this specification.

The major version is justified by the new runtime control plane, persistentledger, configuration schema, delivery state machine, and intentional removalof ambiguous CLI behavior. Preserve user data and offer migration paths, but donot retain interfaces that make cross-provider configuration unsafe.

Compatibility rules:

Existing Claude and Copilot files and settings must be preserved unlessAgentmaster owns the exact value being changed.

Existing Markdown telemetry, evidence, and retrospectives remain readable.Migration imports them; it never deletes them automatically.

--model is removed in v2.0.0. Passing it must fail before writes with amigration message naming --claude-model and --copilot-model.

Existing generated workers remain the default output when no runtime overrideis selected, apart from deliberate v2 frontmatter and orchestration changes.

Ledger schema migrations are forward-only, transactional, versioned, andbacked up before any destructive rewrite.

A v1 installation can be upgraded in place and uninstalled without losinglater user edits.

3. Required outcomes

Claude coordinator, orchestrator, implementer, reviewer, and git-publisherroles have explicit model configuration. Claude roles that support efforthave explicit effort configuration.

Copilot coordinator and implementer models are configurable. Do not emit aneffort field for Copilot agents unless the target schema demonstrably addssupport before implementation.

Claude implementer defaults remain sonnet and medium; Copilot implementerdefaults remain claude-sonnet-4.6 unless upstream deliberately changes.

Claude auto-compaction can be explicitly set to 50%, with accurate messagingthat it affects the main Claude session and every subagent.

The implementer does not receive a scout-spawning tool by default. Discovery,parallel reading, and independent verification remain coordinator-owned.

The orchestrator actively owns preflight, task state, dependency readiness,context packaging, risk routing, budget enforcement, evidence sufficiency,delivery, review, and retrospective completion.

agentmaster-execute cannot report completion while delivery, current-headCI, required review, merge, or retrospective gates remain incomplete.

A dedicated git-publisher agent performs bounded git/PR operations from anapproved change set. Implementers never push or merge by default.

SKILL.md work is routed through a task-scoped writing-skills capability.

Persistent structured state is stored by default at~/.agentmaster/ledger.sqlite3; the path and feature are configurable.

Ledger memories can be filtered by project, linked to other memories andevidence, targeted to projects/procedures/tasks, and promoted only throughexplicit validation.

Runs, agents, model calls, tool calls, compactions, artifacts, evidence,procedures, tasks, delivery attempts, CI checks, reviews, retrospectives,memories, retrievals, and evaluations are queryable.

Token accounting captures provider-reported input, output, reasoning,cache-read, cache-write, and billed tokens when available, withoutfabricating absent values.

Cost is stored as integer micro-units with pricing provenance; retrospectiveworth is derived from observable outcome, quality, cost, latency, reuse,and evidence rather than a single subjective score.

The retrospective capability can query stable read-only ledger viewsdirectly. All writes go through a narrow validated command surface.

Retrieval uses project filters, lifecycle state, recency, confidence,evidence quality, and bounded link traversal. FTS5 is the initial searchmechanism; embeddings require measured need and a later decision record.

Dry-run reports every installer mutation, including Agentmaster config,Claude settings.json, owned-state, and ledger initialization.

Failed installation batches roll back. Uninstall removes only owned stateand preserves subsequent user edits.

Tests use strict pytest configuration, deterministic isolation, warnings aserrors, and separately runnable unit, subprocess, and integration slices.

CI, documentation, generated files, migrations, release bundle, andchecksums remain aligned.

The complete work is merged from develop to main and published asv2.0.0 through the repository release workflow.

4. Non-goals

Do not turn Agentmaster into a hosted service or multi-user database server.

Do not add a vector database, embedding dependency, or semantic-search API inv2.0.0.

Do not store full prompts, secrets, or command output by default.

Do not let retrospectives automatically edit skills, agents, policies, orsource code.

Do not let the orchestrator change architecture, scope, or acceptance criteriawithout an explicit user decision.

Do not let implementers spawn unrestricted nested subagents.

Do not create a general workflow engine, ORM, YAML parser, or provider-neutralclass hierarchy.

Do not add Rich, Click, Typer, PyYAML, SQLAlchemy, or another runtimedependency. Runtime code remains standard-library-only.

Do not promise exact monetary cost when the provider does not expose enoughusage or pricing information.

5. Non-negotiable engineering constraints

Do not add from __future__ import annotations. Remove all existing uses.

Do not retain pre-3.14 compatibility shims. requires-python = ">=3.14" isthe runtime contract.

Use Python 3.14 behavior and typing directly: built-in generics, X | None,PEP 695 aliases where useful, deferred annotations, StrEnum, and slotteddataclasses.

Keep production functions fully typed. Tests may omit return annotations, butshared fixtures and factories must expose useful types.

Use precise JSON types or domain records instead of bare dict, broad Any,and opaque argparse.Namespace beyond the CLI boundary.

Keep functions under 50 logical lines unless a documented invariant makes asplit less readable. Keep cyclomatic complexity at or below 10 and nesting atthree levels or fewer.

Prefer named intermediate values, early returns, and small domain-namedfunctions. Do not add generic utils.py modules, boolean flag piles, orone-line abstractions.

Catch specific installer and ledger failures. A hook may fail open only at anamed boundary with a test proving the fallback.

Never interpolate SQL identifiers from untrusted input. Parameterize values;expose only allow-listed views and sort keys.

Use UTC timestamps in RFC 3339 text and monotonic durations in integermilliseconds. Use UUIDv7 when available in the chosen standard-libraryimplementation strategy, otherwise sortable timestamp prefixes plus securerandom identifiers.

Store currency as integer micro-USD or another explicitly named integer unit;never use binary floating point for money.

Foreign keys are enabled on every ledger connection. Migrations run in animmediate transaction and are idempotent at the version boundary.

The ledger is supported only on a local filesystem. Detect or document thatnetwork filesystems are unsupported for WAL mode.

Keep raw large evidence in content-addressed artifact files; store hashes,metadata, and provenance in SQLite.

Do not manually edit generated worker files as source of truth. Edit themanifest/shared source and run python install.py sync.

Preserve the no-force-push workflow. Never merge a stale reviewed commit.

6. Research and design basis

The architecture follows a conservative reading of current agent-memory andsoftware-agent research:

SQLite is appropriate for application-local state with low write concurrency,transactional updates, backup support, and portable single-file storage.It is not a replacement for a server database when many machines writeconcurrently. See Appropriate Uses for SQLite.

WAL improves local reader/writer concurrency, but its operational constraintsand version-specific recovery behavior require a runtime gate, local-filesystempolicy, short transactions, and a rollback-journal fallback. SeeSQLite Write-Ahead Logging.

Reflection improves behavior when verbal feedback is retained and reused, butunvalidated reflection can reinforce mistakes. SeeReflexion.

Tiered memory and deliberate context movement are more useful than treating acontext window as permanent storage. SeeMemGPT.

Retrieval, reflection, and planning become more useful when memories haverecency, importance, and relationship structure. SeeGenerative Agents.

Long-term agent memory must be evaluated for accurate retrieval, test-timelearning, long-range understanding, and selective forgetting—not only recall.See MemoryAgentBench.

Tool interfaces and repository navigation strongly affect coding-agentperformance; structured, inspectable actions are preferable to hidden promptconvention. See SWE-agent.

Reusable skill libraries can improve future work, but procedures should beversioned and evaluated rather than silently overwritten. SeeVoyager.

Provenance should model entities, activities, and responsible agents so thatevidence and conclusions remain auditable. See theW3C PROV data model.

These sources motivate the design; they do not prove that every stored memoryis useful. Agentmaster must measure retrieval use, downstream outcomes, andcounterexamples before promotion.

7. Target architecture

flowchart TD
    A["Plan and user constraints"] --> B["Orchestrator control plane"]
    B --> C["Implementers and coordinator-owned scouts"]
    C --> D["Evidence and verification"]
    D --> E["Git publisher, CI, and review"]
    E --> F["Merge and retrospective"]
    F --> G["Candidate memories and procedure evaluations"]
    G --> H["Validate, scope, and promote"]
    H --> B
    B <--> L["Project-aware SQLite ledger"]
    C --> L
    D --> L
    E --> L
    F --> L

The orchestrator is the sole control-plane owner. It delegates repository edits,independent discovery, review, and git publication to purpose-specific agents,but it owns state transitions and decides what is ready to run. State lives inthe ledger and compact context packs, not only in the conversation transcript.

8. Agent boundaries and cost policy

Role

Default purpose

May edit source

May spawn scouts

May perform git publication

Recommended Claude tier

Orchestrator

Preflight, dispatch, gates, budgets, context

No

Yes, selectively

Delegates only

Sonnet / medium

Implementer

Execute one bounded task

Yes

No by default

No

Sonnet / medium

Scout

Read/search/verify a narrow question

No

No

No

Cheapest capable model

Reviewer

Independent correctness/safety review

No

May request evidence, not edits

No

Opus / high

Git publisher

Commit, push, PR, checks, merge gate

Only PR metadata/scripts if tasked

No

Yes, bounded

Sonnet / low

Retrospective

Analyze outcomes and propose candidates

No

No

No

Sonnet / medium

Implementer-spawned scouts are intentionally disabled by default. Giving everyworker another delegation layer adds token duplication, coordination overhead,and hidden context divergence. The orchestrator may dispatch a scout when aquestion is independent, read-heavy, parallelizable, and cheaper than consumingimplementer context. An explicit future configuration may allow one boundedread-only scout, but v2.0.0 must not make that the default.

Reviewer independence is mandatory: the reviewer must not be the implementingagent and must receive the plan, acceptance criteria, diff, tests, and evidencefor the exact commit under review.

9. Orchestrator authority and invariants

The orchestrator must:

validate repository, branch, worktree, plan schema, dependencies, requiredtools, configuration, ledger health, and budget before dispatch;

maintain a live task graph with explicit ready, running, blocked, failed,review-required, and complete states;

build a bounded context pack for each role instead of forwarding the entireaccumulated transcript;

route by risk, ambiguity, independence, and cost;

record every state transition and its evidence;

stop new dispatch when a hard budget is exceeded or a required gate fails;

recover idempotently after interruption by reconciling ledger state with gitand GitHub state;

require delivery, CI, independent review, merge, and retrospective accordingto the selected delivery mode.

The orchestrator must not:

edit repository files directly;

approve its own implementation or reviewer verdict;

alter architecture, requirements, or acceptance criteria without user input;

infer that a passing test proves criteria not covered by that test;

promote a memory or procedure globally from a single project outcome;

hide budget exhaustion by silently switching models or dropping verification.

9.1 Execution state machine

stateDiagram-v2
    [*] --> Planned
    Planned --> Preflight
    Preflight --> Executing: valid
    Preflight --> Blocked: missing authority or dependency
    Executing --> Verifying
    Verifying --> FixesRequired: failed evidence
    FixesRequired --> Executing
    Verifying --> DeliveryPending: acceptance met
    DeliveryPending --> CIPending
    CIPending --> FixesRequired: checks fail
    CIPending --> ReviewRequired: exact head is green
    ReviewRequired --> Reviewing
    Reviewing --> FixesRequired: NEEDS FIXES
    Reviewing --> MergePending: GOOD on exact head
    MergePending --> Merged
    Merged --> RetrospectivePending
    RetrospectivePending --> Complete
    Complete --> [*]

Blocked, Failed, and Cancelled are terminal for the current attempt but maybe resumed by creating a new attempt linked to the prior one. No stop hook maytranslate an incomplete or failed state into success.

Feedback capture attaches at the RetrospectivePending→Complete transition:the run's retrospective must exist before feedback is solicited, and afeedback prompt never blocks the transition to Complete from completing.

9.2 Completion by delivery mode

Mode

Completion requirement

local

Accepted local changes, tests, evidence, and retrospective

commit

Local requirements plus intentional commit and retrospective

pull-request

Pushed commit, PR, green current-head CI, GOOD review, retrospective

merge

Pull-request requirements plus merge verification and retrospective

The repository plan in this specification always uses merge mode.

9.3 Context-pack contract

Each dispatched agent receives a generated context pack containing only:

task ID, project ID, branch, base SHA, expected head constraints;

objective, non-goals, acceptance criteria, dependencies, and allowed files;

selected memories with source, scope, confidence, and counterevidence;

relevant procedure version and invokable harness commands;

model, effort, token/cost/time budgets, and stop conditions;

required evidence and handoff schema.

The pack records which memories were retrieved and their rank. It must not embedsecrets, full historical transcripts, or unrelated project memories.

9.4 Evidence sufficiency

A task is verifiable only when each acceptance criterion has at least oneevidence record or an explicit reason that manual verification is required.Evidence may be a test result, command result, diff inspection, generated paritycheck, artifact hash, CI check, or reviewer finding. A statement such as “testspass” is not sufficient without command, exit status, timestamp, and commit SHA.

10. Audit findings this plan must address

10.1 Python and installer structure

from __future__ import annotations remains in install.py, installer targetmodules, and telemetry reporting despite the Python 3.14 minimum.

install.py contains a redundant manual runtime guard and mixes parsing,prompting, validation, configuration resolution, target installation, andpresentation.

JSON/configuration values are often bare dict or Any; severalTYPE_CHECKING blocks add ceremony without value under deferred annotations.

One legacy --model value is reused across Claude and Copilot even thoughprovider slugs differ.

Implementer models are frozen in generated text; Claude implementer effort isomitted and inherits ambient session effort.

Interactive and noninteractive runs do not present one resolved plan beforewrites.

Model replacement is duplicated and is not strictly bounded to the firstfrontmatter block.

10.2 Installation safety and compaction

Claude settings.json is changed outside the normal plan, dry-run report, andbatch backup path.

A multi-file failure may leave a partially applied install even though thecurrent comments describe installation as transactional.

Timestamp-only backup and compaction snapshot names can collide.

Updating user-owned files does not explicitly preserve mode.

Claude uninstall may remove files before discovering malformed settings.

PreCompact observes compaction but does not choose its threshold.

CLAUDE_AUTOCOMPACT_PCT_OVERRIDE is process-wide; it affects the main sessionand subagents, not only the implementer.

Compaction telemetry does not reliably identify the compacting agent or thepre-compaction token count.

10.3 Orchestration and delivery

agentmaster-execute is described as a dispatch agent and intentionally doesnot implement, but it also lacks a durable control-plane state model.

The skill asks for agentmaster-review in prose; no state transition or stophook proves that the review occurred for the current commit.

CI state, review SHA, PR SHA, and merge eligibility are not reconciled as oneexact-head invariant.

No dedicated agent owns bounded git publication. The result depends on theactive agent remembering commit, push, PR-template, check-watch, and mergesteps.

SKILL.md tasks have no explicit capability-routing rule.

There is no persisted risk score, context budget, cost budget, evidence map,dependency graph, or recovery cursor for an interrupted run.

10.4 Memory, evidence, and retrospective state

Markdown telemetry and retrospective files are useful for humans but are nota normalized, queryable execution ledger.

Memories cannot be consistently filtered by project, linked to sources andcounterevidence, or promoted with an auditable state transition.

Token usage is incomplete and cannot be attributed to a model call, agent,task, project, procedure version, or outcome.

“Worth” has no defined dimensions or counterfactual baseline.

Procedure reuse is not linked to later success/failure, so recursiveimprovement risks rewarding attractive prose instead of effective behavior.

There is no durable record of what memory was retrieved, whether an agent usedit, and what happened afterward.

10.5 Tests, repository, CI, and release

CLI subprocess tests are mixed into parity tests.

Only one pytest marker is registered; subprocess and integration boundariesare inconsistently marked.

Pytest lacks strict configuration, warnings-as-errors, strict xfail behavior,and useful short failure summaries.

Fixtures inherit ambient user environment and depend on implicit interpreterbehavior.

CI uses uv sync without --locked and lacks explicit least privilege,timeout, and concurrency cancellation.

There is no PR template enforcing acceptance evidence and current-head review.

Release assembly is embedded in workflow shell, lacks an archive-content test,and does not publish a checksum asset.

11. Final installer interface

The exact option spelling is part of the v2.0.0 acceptance contract.

python install.py install \
  --target claude|copilot|all \
  [--config PATH] \
  [--agentmaster-home PATH] \
  [--claude-model MODEL] \
  [--copilot-model MODEL] \
  [--claude-orchestrator-model MODEL] \
  [--claude-orchestrator-effort low|medium|high|xhigh|max] \
  [--claude-implementer-model MODEL] \
  [--claude-implementer-effort low|medium|high|xhigh|max] \
  [--claude-review-model MODEL] \
  [--claude-review-effort low|medium|high|xhigh|max] \
  [--claude-git-publisher-model MODEL] \
  [--claude-git-publisher-effort low|medium|high|xhigh|max] \
  [--copilot-implementer-model MODEL] \
  [--auto-compact-percent 1..100] \
  [--clear-auto-compact-override] \
  [--ledger-path PATH] \
  [--no-ledger] \
  [--artifact-dir PATH] \
  [--delivery-mode local|commit|pull-request|merge] \
  [--no-input] \
  [--dry-run]

Compatibility and validation:

Reject --model with an actionable v2 migration message. Never silently mapone provider slug to both targets.

Reject a target-specific option when its target is not selected.

Reject simultaneous --no-ledger and --ledger-path.

--config loads a versioned TOML file; explicit CLI options override itsvalues. Environment variables are limited to documented path overrides andnever override an explicit CLI flag.

Validate all options and source-file frontmatter before the first write.

--no-input and non-TTY stdin must never call input().

Dry-run may read and validate the ledger but must not create a directory,database, backup, migration, journal, artifact, or settings file.

11.1 Recommended defaults

Role or setting

Claude default

Copilot default

Rationale

Coordinator

opus

claude-opus-4.8

Planning and architectural judgment

Orchestrator

sonnet, medium

Target-supported coordinator model

Persistent control work, not final review

Implementer

sonnet, medium

claude-sonnet-4.6

Plans contain hard decisions; worker executes

Reviewer

opus, high

Target-supported frontier model

Independent correctness and safety gate

Git publisher

sonnet, low

Target-supported economical model

Bounded mechanical publication

Auto-compaction

Preserve

Unsupported

Global Claude behavior must be opt-in

Ledger

Enabled, structured metadata

Enabled, structured metadata

Durable audit and learning

Raw output capture

Failures only after redaction

Same

Debug value without transcript hoarding

Delivery mode

local outside repository plans

Same

External mutation remains explicit

If a listed model slug is no longer accepted when implementation begins, usethe repository/provider-supported equivalent and document the change. Do notprobe paid endpoints during install.

Interactive mode prompts only for omitted settings, explains materialtradeoffs, and shows a single resolved summary before asking to proceed. Example:

Agentmaster
  home                    /home/user/.agentmaster
  ledger                  /home/user/.agentmaster/ledger.sqlite3
  artifacts               /home/user/.agentmaster/artifacts
  delivery mode           local

Claude Code
  destination             /home/user/.claude
  coordinator             opus
  orchestrator            sonnet / medium
  implementer             sonnet / medium
  reviewer                opus / high
  git publisher           sonnet / low
  auto-compaction         50% (main session and all subagents)

Copilot
  destination             /home/user/.copilot
  coordinator             claude-opus-4.8
  implementer             claude-sonnet-4.6
  effort                  unsupported

12. Runtime configuration contract

Agentmaster runtime configuration lives at~/.agentmaster/config.toml by default. It contains behavior and paths, notsecrets. The installer owns only fields recorded in its versioned install-statefile. Unknown keys must survive a read/modify/write.

schema_version = 1

[paths]
ledger = "~/.agentmaster/ledger.sqlite3"
artifacts = "~/.agentmaster/artifacts"

[orchestration]
delivery_mode = "local"
max_parallel_tasks = 2
implementer_scouts = false
context_pack_token_limit = 12000
memory_link_depth = 2

[orchestration.budget]
max_run_tokens = 0          # 0 means no configured hard token ceiling
max_run_micro_usd = 0       # 0 means unavailable/unlimited, not free
max_run_minutes = 0

[agents.claude.orchestrator]
model = "sonnet"
effort = "medium"

[agents.claude.implementer]
model = "sonnet"
effort = "medium"

[agents.claude.reviewer]
model = "opus"
effort = "high"

[agents.claude.git_publisher]
model = "sonnet"
effort = "low"

[agents.copilot.implementer]
model = "claude-sonnet-4.6"

[ledger]
enabled = true
journal_mode = "auto"
busy_timeout_ms = 5000
raw_output = "failures"
redaction = "standard"
retention_days = 180

[memory]
default_visibility = "project"
minimum_promotion_evidence = 2
allow_global_retrieval = true

Configuration rules:

Expand ~ only at the filesystem boundary; summaries show normalized paths.

Reject unknown enum values and invalid numeric ranges with a dotted key path.

Preserve unknown future tables/keys when editing managed values.

A zero budget means no configured ceiling or unavailable accounting. UI textmust never label it as zero usage or zero cost.

implementer_scouts remains false and experimental in v2.0.0. Enabling itrequires an explicit config edit and still permits at most one read-only,bounded scout; the CLI need not expose it.

Secrets and provider tokens are never accepted in this file.

13. Frontmatter and generated-agent contract

Agentmaster needs a strict updater for the first YAML frontmatter block, not ageneral YAML parser.

Find the first leading --- block and its closing delimiter.

Replace or insert only allow-listed scalar keys.

Reject duplicate managed keys, missing delimiters, multiline replacementvalues, aliases, tags, and attempts to edit outside the block.

Preserve field order, comments, platform-specific lists, and the Markdown bodybyte-for-byte.

Runtime overrides affect only installation destinations. The manifest remainscanonical and python install.py sync remains deterministic.

Add Claude effort: medium to the canonical implementer.

Add explicit model/effort frontmatter to orchestrator, reviewer, and gitpublisher where the target supports it.

Do not emit Copilot effort fields.

14. Installer transaction and ownership model

Every mutation is represented as a typed plan before apply:

file create/update/remove;

mode change;

Agentmaster TOML update;

Claude settings update;

owned-state update;

ledger initialize/migrate;

artifact-directory create;

uninstall restoration.

Apply requirements:

Create a collision-safe backup directory using a sortable timestamp andrandom suffix.

Preserve the destination mode unless a plan explicitly changes it.

Use same-filesystem temporary files, fsync where durability matters, andatomic replacement.

Track created and updated paths. On failure, restore updates and remove filescreated by that batch; retain diagnostic backups.

Apply database migrations before external file replacement only when rollbackcan restore the prior database backup. Otherwise stage the migrated databaseand atomically replace it with the batch.

Report original failure and rollback result separately.

Uninstall plans all validation and restoration before deleting any file.

Restore a managed value only if its current value equals Agentmaster's lastinstalled value. Preserve later user edits.

Owned state is versioned and stored under the Agentmaster home and the target'smanaged directory where necessary. Store only prior presence/value, installedvalue, ownership token, target, and install version—never a wholesale copy ofuser configuration.

15. Claude auto-compaction contract

--auto-compact-percent accepts an integer from 1 through 100.--clear-auto-compact-override is mutually exclusive.

Interactive Claude installation offers:

Preserve current/default behavior.

Set 50% (recommended for long Agentmaster execution sessions).

Set a custom percentage.

Clear an existing Agentmaster-managed override.

Noninteractive install preserves current behavior unless explicitly configured.When selected, manage:

{
  "env": {
    "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "50"
  }
}

The installer and documentation must say that this affects the main Claudeconversation and all subagents. Earlier compaction reduces working-contextpressure but may discard detail and disrupt cache continuity; it is not aper-implementer control.

On reinstall, preserve the original pre-Agentmaster value. On clear/uninstall,restore it only if Agentmaster still owns the current value.

16. Ledger storage and operational contract

16.1 Location, permissions, and connections

Default database: ~/.agentmaster/ledger.sqlite3.

Accept a configured absolute or user-relative path. The older proposed nameledger.sqlite.db may be recognized during migration, but new installs usethe conventional .sqlite3 suffix.

Default artifact root: ~/.agentmaster/artifacts/sha256/.

Create the Agentmaster directory with mode 0700, database and backups withmode 0600, and artifacts with least-readable practical modes.

Open foreign keys, set a finite busy timeout, keep write transactions short,and use one connection per process or thread boundary.

Prefer WAL only when the runtime SQLite version contains the WAL-reset fix(3.51.3 or a documented patched backport) and the path is a local filesystem.Otherwise use DELETE journaling and record the reason in ledger_health.

Use SQLite's online backup API for consistent backups. Checkpoint WAL beforerelease diagnostics or portable copies.

Retrying BUSY uses bounded jittered backoff. Hooks fail open after recordinga local diagnostic when possible; installer and migration commands fail closed.

16.2 Data minimization and retention

Structured metadata is enabled by default. Raw request/response and commandoutput capture defaults to failures only, after redaction. Store a digest andtruncated preview in SQLite; store permitted full payloads as content-addressedartifacts.

Redaction removes or masks:

values matching documented secret-key names;

known provider tokens and authorization headers;

environment values not explicitly allow-listed;

filesystem paths outside project and Agentmaster roots when not needed;

user-configurable regex patterns.

Retention is policy-driven. Deleting expired raw artifacts does not delete thehashed evidence record; it marks content unavailable and retains provenance.Memories and retrospectives have independent lifecycle state and are not purgedmerely because source output expires.

16.3 Schema conventions

Primary IDs are text identifiers generated by Agentmaster.

Timestamps are non-null UTC text; durations are integer milliseconds.

Token fields are nullable non-negative integers. NULL means unavailable;zero means the provider explicitly reported zero.

Every mutable knowledge entity has created_at, updated_at, lifecyclestate, and provenance.

Provider-specific usage details go into canonical columns when understood anda redacted provider_usage_json field for forward compatibility.

Use check constraints for enums/ranges and indexes for foreign keys and commonproject/time/state queries.

Use triggers only for FTS synchronization and simple immutable audit fields.Business transitions remain typed Python operations with tests.

16.4 Index policy

Every foreign key in §17 has a named index, and every common project/time/state/entrypoint query path has a matching named index. This makes the ruleat §16.3 (indexes for foreign keys and common project/time/state queries)concrete rather than left to migration authors' discretion.

CREATE INDEX idx_run_project_id ON RUN(project_id);
CREATE INDEX idx_run_user_session_id ON RUN(user_session_id);
CREATE INDEX idx_run_parent_run_id ON RUN(parent_run_id);
CREATE INDEX idx_task_run_id ON TASK(run_id);
CREATE INDEX idx_task_parent_task_id ON TASK(parent_task_id);
CREATE INDEX idx_task_dependency_task_id ON TASK_DEPENDENCY(task_id);
CREATE INDEX idx_task_dependency_depends_on_task_id ON TASK_DEPENDENCY(depends_on_task_id);
CREATE INDEX idx_agent_session_run_id ON AGENT_SESSION(run_id);
CREATE INDEX idx_agent_session_task_id ON AGENT_SESSION(task_id);
CREATE INDEX idx_agent_session_parent_session_id ON AGENT_SESSION(parent_session_id);
CREATE INDEX idx_agent_session_entrypoint_id ON AGENT_SESSION(entrypoint_id);
CREATE INDEX idx_model_call_agent_session_id ON MODEL_CALL(agent_session_id);
CREATE INDEX idx_tool_call_agent_session_id ON TOOL_CALL(agent_session_id);
CREATE INDEX idx_tool_call_task_id ON TOOL_CALL(task_id);
CREATE INDEX idx_tool_call_entrypoint_id ON TOOL_CALL(entrypoint_id);
CREATE INDEX idx_compaction_event_agent_session_id ON COMPACTION_EVENT(agent_session_id);
CREATE INDEX idx_compaction_event_snapshot_artifact_id ON COMPACTION_EVENT(snapshot_artifact_id);
CREATE INDEX idx_delivery_attempt_run_id ON DELIVERY_ATTEMPT(run_id);
CREATE INDEX idx_ci_check_delivery_attempt_id ON CI_CHECK(delivery_attempt_id);
CREATE INDEX idx_review_delivery_attempt_id ON REVIEW(delivery_attempt_id);
CREATE INDEX idx_review_reviewer_session_id ON REVIEW(reviewer_session_id);
CREATE INDEX idx_review_summary_artifact_id ON REVIEW(summary_artifact_id);
CREATE INDEX idx_review_finding_review_id ON REVIEW_FINDING(review_id);
CREATE INDEX idx_review_finding_evidence_id ON REVIEW_FINDING(evidence_id);
CREATE INDEX idx_artifact_project_id ON ARTIFACT(project_id);
CREATE INDEX idx_evidence_run_id ON EVIDENCE(run_id);
CREATE INDEX idx_evidence_task_id ON EVIDENCE(task_id);
CREATE INDEX idx_evidence_artifact_id ON EVIDENCE(artifact_id);
CREATE INDEX idx_retrospective_run_id ON RETROSPECTIVE(run_id);
CREATE INDEX idx_retro_observation_retrospective_id ON RETRO_OBSERVATION(retrospective_id);
CREATE INDEX idx_memory_origin_project_id ON MEMORY(origin_project_id);
CREATE INDEX idx_memory_supersedes_memory_id ON MEMORY(supersedes_memory_id);
CREATE INDEX idx_memory_scope_memory_id ON MEMORY_SCOPE(memory_id);
CREATE INDEX idx_memory_scope_project_id ON MEMORY_SCOPE(project_id);
CREATE INDEX idx_memory_target_memory_id ON MEMORY_TARGET(memory_id);
CREATE INDEX idx_memory_link_source_memory_id ON MEMORY_LINK(source_memory_id);
CREATE INDEX idx_memory_link_target_memory_id ON MEMORY_LINK(target_memory_id);
CREATE INDEX idx_memory_evidence_memory_id ON MEMORY_EVIDENCE(memory_id);
CREATE INDEX idx_memory_evidence_evidence_id ON MEMORY_EVIDENCE(evidence_id);
CREATE INDEX idx_memory_evidence_observation_id ON MEMORY_EVIDENCE(observation_id);
CREATE INDEX idx_procedure_project_id ON PROCEDURE(project_id);
CREATE INDEX idx_procedure_version_procedure_id ON PROCEDURE_VERSION(procedure_id);
CREATE INDEX idx_procedure_version_artifact_id ON PROCEDURE_VERSION(artifact_id);
CREATE INDEX idx_procedure_use_procedure_version_id ON PROCEDURE_USE(procedure_version_id);
CREATE INDEX idx_procedure_use_task_id ON PROCEDURE_USE(task_id);
CREATE INDEX idx_procedure_use_agent_session_id ON PROCEDURE_USE(agent_session_id);
CREATE INDEX idx_evaluation_memory_id ON EVALUATION(memory_id);
CREATE INDEX idx_evaluation_procedure_version_id ON EVALUATION(procedure_version_id);
CREATE INDEX idx_evaluation_project_id ON EVALUATION(project_id);
CREATE INDEX idx_evaluation_evaluator_session_id ON EVALUATION(evaluator_session_id);
CREATE INDEX idx_evaluation_metric_evaluation_id ON EVALUATION_METRIC(evaluation_id);
CREATE INDEX idx_feedback_user_session_id ON FEEDBACK(user_session_id);
CREATE INDEX idx_feedback_run_id ON FEEDBACK(run_id);
CREATE INDEX idx_feedback_task_id ON FEEDBACK(task_id);
CREATE INDEX idx_feedback_memory_id ON FEEDBACK(memory_id);
CREATE INDEX idx_run_state ON RUN(state);
CREATE INDEX idx_task_state ON TASK(state);
CREATE INDEX idx_run_started_at ON RUN(started_at);
CREATE INDEX idx_task_started_at ON TASK(started_at);
CREATE INDEX idx_entrypoint_kind_active ON ENTRYPOINT(kind, active);

Migrations that add a table or FK add its index in the same migration. Adoctor check flags any FK column missing a covering index.

17. Ledger entity-relationship model

The schema is split into execution/delivery and knowledge/provenance views forreadability. They are one database.

17.1 Execution, usage, and delivery

erDiagram
    USER_SESSION ||--o{ RUN : initiates
    PROJECT ||--o{ RUN : owns
    RUN ||--o{ TASK : contains
    RUN ||--o{ AGENT_SESSION : dispatches
    TASK ||--o{ AGENT_SESSION : executes
    ENTRYPOINT ||--o{ AGENT_SESSION : originates
    ENTRYPOINT ||--o{ TOOL_CALL : originates
    AGENT_SESSION ||--o{ MODEL_CALL : makes
    AGENT_SESSION ||--o{ TOOL_CALL : invokes
    AGENT_SESSION ||--o{ COMPACTION_EVENT : compacts
    TASK ||--o{ TASK_DEPENDENCY : depends
    RUN ||--o{ DELIVERY_ATTEMPT : delivers
    DELIVERY_ATTEMPT ||--o{ CI_CHECK : observes
    DELIVERY_ATTEMPT ||--o{ REVIEW : receives
    REVIEW ||--o{ REVIEW_FINDING : contains

    USER_SESSION {
        text user_session_id PK
        text harness_session_id
        text created_at
    }
    ENTRYPOINT {
        text id PK
        text kind
        text name
        text source_path
        integer active
        text created_at
    }
    PROJECT {
        text id PK
        text canonical_root
        text remote_identity
        text display_name
        text fingerprint
        text created_at
        text last_seen_at
    }
    RUN {
        text id PK
        text project_id FK
        text user_session_id FK
        text parent_run_id FK
        text plan_id
        text delivery_mode
        text state
        text base_sha
        text head_sha
        text started_at
        text ended_at
        integer duration_ms
    }
    TASK {
        text id PK
        text run_id FK
        text parent_task_id FK
        text title
        text state
        text risk_level
        integer sequence_no
        text acceptance_json
        text started_at
        text ended_at
    }
    TASK_DEPENDENCY {
        text task_id FK
        text depends_on_task_id FK
        text dependency_kind
    }
    AGENT_SESSION {
        text id PK
        text run_id FK
        text task_id FK
        text parent_session_id FK
        text entrypoint_id FK
        text role
        text provider
        text model
        text effort
        text state
        integer context_limit_tokens
        text started_at
        text ended_at
    }
    MODEL_CALL {
        text id PK
        text agent_session_id FK
        text provider_call_id
        text model
        text effort
        integer input_tokens
        integer output_tokens
        integer reasoning_tokens
        integer cache_read_tokens
        integer cache_write_tokens
        integer billed_tokens
        integer context_estimate_tokens
        integer duration_ms
        integer cost_micro_usd
        text pricing_source
        text stop_reason
        text provider_usage_json
        text created_at
    }
    TOOL_CALL {
        text id PK
        text agent_session_id FK
        text task_id FK
        text entrypoint_id FK
        text tool_name
        text operation
        text state
        integer duration_ms
        integer exit_code
        text input_digest
        text output_digest
        text created_at
    }
    COMPACTION_EVENT {
        text id PK
        text agent_session_id FK
        text trigger
        integer threshold_percent
        integer pre_tokens
        integer post_tokens
        text snapshot_artifact_id FK
        text created_at
    }
    DELIVERY_ATTEMPT {
        text id PK
        text run_id FK
        integer attempt_no
        text branch
        text base_sha
        text head_sha
        integer pr_number
        text pr_url
        text state
        text created_at
        text completed_at
    }
    CI_CHECK {
        text id PK
        text delivery_attempt_id FK
        text provider_check_id
        text name
        text head_sha
        text status
        text conclusion
        text url
        text observed_at
    }
    REVIEW {
        text id PK
        text delivery_attempt_id FK
        text reviewer_session_id FK
        text reviewed_sha
        text verdict
        text summary_artifact_id FK
        text created_at
    }
    REVIEW_FINDING {
        text id PK
        text review_id FK
        text severity
        text state
        text criterion_id
        text file_path
        integer line_no
        text summary
        text evidence_id FK
    }

MODEL_CALL rows are append-only. Aggregate views calculate per-run, per-task,per-role, per-model, and per-procedure totals. A model call without providerusage remains a row with null usage and usage_status = 'unavailable'; do notestimate it unless a separately labeled estimator version is recorded.

user_session_id identifies an Agentmaster-generated session distinct from theexternal harness session: user_session_id is the Agentmaster-generated primaryidentifier (text identifiers generated by Agentmaster per §16.3), whileharness_session_id correlates to the external Claude Code session id. RUN.user_session_id is a required FK to USER_SESSION.

ENTRYPOINT records the skill, agent, hook, or command that originated a unit ofwork. AGENT_SESSION.entrypoint_id and TOOL_CALL.entrypoint_id are nullable FKsto ENTRYPOINT: a session or tool call with no identifiable entrypoint recordsNULL rather than a synthetic row. skill/agent/hook rows seed from the installermanifest; command rows seed from the CLI's own registered command table.

17.2 Evidence, memories, retrospectives, and procedures

erDiagram
    PROJECT ||--o{ ARTIFACT : owns
    RUN ||--o{ EVIDENCE : produces
    TASK ||--o{ EVIDENCE : satisfies
    ARTIFACT ||--o{ EVIDENCE : materializes
    RUN ||--o| RETROSPECTIVE : concludes
    RETROSPECTIVE ||--o{ RETRO_OBSERVATION : contains
    RETRO_OBSERVATION ||--o{ MEMORY_EVIDENCE : supports
    MEMORY ||--o{ MEMORY_EVIDENCE : has
    MEMORY ||--o{ MEMORY_SCOPE : visible
    MEMORY ||--o{ MEMORY_TARGET : applies
    MEMORY ||--o{ MEMORY_LINK : source
    MEMORY ||--o{ MEMORY_LINK : destination
    PROCEDURE ||--o{ PROCEDURE_VERSION : versions
    PROCEDURE_VERSION ||--o{ PROCEDURE_USE : used
    TASK ||--o{ PROCEDURE_USE : applies
    EVALUATION ||--o{ EVALUATION_METRIC : measures
    MEMORY ||--o{ EVALUATION : evaluates
    PROCEDURE_VERSION ||--o{ EVALUATION : evaluates
    USER_SESSION ||--o{ FEEDBACK : gives
    RUN ||--o{ FEEDBACK : receives
    TASK ||--o{ FEEDBACK : receives
    MEMORY ||--o{ FEEDBACK : receives

    ARTIFACT {
        text id PK
        text project_id FK
        text sha256
        text media_type
        integer byte_size
        text relative_path
        text retention_class
        text redaction_state
        text created_at
        text expires_at
    }
    EVIDENCE {
        text id PK
        text run_id FK
        text task_id FK
        text artifact_id FK
        text evidence_kind
        text criterion_id
        text command
        integer exit_code
        text commit_sha
        text summary
        text created_at
    }
    RETROSPECTIVE {
        text id PK
        text run_id FK
        text status
        text outcome
        text summary
        text created_at
        text completed_at
    }
    RETRO_OBSERVATION {
        text id PK
        text retrospective_id FK
        text observation_kind
        text claim
        text confidence
        text counterfactual
        text created_at
    }
    MEMORY {
        text id PK
        text origin_project_id FK
        text state
        text memory_kind
        text title
        text content
        text confidence
        integer usefulness_count
        integer harmful_count
        text supersedes_memory_id FK
        text created_at
        text updated_at
    }
    MEMORY_SCOPE {
        text memory_id FK
        text scope_kind
        text project_id FK
        text include_descendants
        text created_at
    }
    MEMORY_TARGET {
        text memory_id FK
        text target_kind
        text target_key
        text created_at
    }
    MEMORY_LINK {
        text source_memory_id FK
        text target_memory_id FK
        text link_kind
        real weight
        text created_at
    }
    MEMORY_EVIDENCE {
        text memory_id FK
        text evidence_id FK
        text observation_id FK
        text relation
        text strength
        text created_at
    }
    PROCEDURE {
        text id PK
        text project_id FK
        text name
        text scope
        text state
        text created_at
    }
    PROCEDURE_VERSION {
        text id PK
        text procedure_id FK
        integer version_no
        text content_hash
        text artifact_id FK
        text status
        text created_at
    }
    PROCEDURE_USE {
        text id PK
        text procedure_version_id FK
        text task_id FK
        text agent_session_id FK
        text outcome
        text created_at
    }
    EVALUATION {
        text id PK
        text memory_id FK
        text procedure_version_id FK
        text project_id FK
        text evaluator_session_id FK
        text evaluation_kind
        text decision
        text created_at
    }
    EVALUATION_METRIC {
        text evaluation_id FK
        text metric_name
        integer value_microunits
        text unit
        text method
    }
    FEEDBACK {
        text id PK
        text user_session_id FK
        text run_id FK
        text task_id FK
        text memory_id FK
        integer rating
        text comment
        text created_at
    }

FEEDBACK.task_id and FEEDBACK.memory_id are nullable FKs; user_session_id andrun_id are required. rating is a tri-state integer (CHECK rating BETWEEN -1AND 1) mapping harmful/neutral/helpful directly onto memory_access'shelpful/harmful semantics and the check-constraint rule in §16.3. FEEDBACK iswritten by agentmaster ledger record-feedback (§19) and the feedback-captureflow attached at RetrospectivePending→Complete (§9.1); it is consumed whencreating memory candidates.

17.3 Provenance and project scoping invariants

origin_project_id records where a memory was learned. Visibility is definedindependently by MEMORY_SCOPE.

scope_kind is project, project_family, or global. A project-scoped rowmust name a project. A global row must not.

Default retrieval includes the current project plus validated global memory.It excludes other projects even when terms match.

Project identity uses canonical root, normalized remote identity, and a stablefingerprint. A moved checkout can be relinked without creating a new project;a fork with a different remote is a different project unless explicitlygrouped into a project family.

MEMORY_LINK.link_kind is one of supports, contradicts, refines,supersedes, derived_from, or related.

Retrieval follows at most two links by default and applies a decaying weight.It never performs unbounded recursive traversal.

All conclusions link to evidence and the agent activity that produced them,following the entity/activity/agent separation of W3C PROV.

17.4 Memory lifecycle

stateDiagram-v2
    [*] --> Candidate
    Candidate --> Validated: independent evidence
    Candidate --> Rejected: contradicted or unsafe
    Validated --> Active: approved scope
    Active --> Superseded: better memory
    Active --> Archived: stale or unused
    Active --> Rejected: harmful evidence
    Superseded --> Archived
    Rejected --> Archived

Rules:

A retrospective creates candidate, never active.

Validation must use evidence not authored solely by the same session thatproposed the candidate.

Project activation requires one successful independent reuse or a humanapproval linked as evidence.

Global promotion requires successful evidence from at least two distinctprojects, no unresolved high-severity counterevidence, and explicit revieweror human approval.

A memory may be demoted when it increases failures, cost, or review findings.

Supersession creates a new memory and link; it does not overwrite history.

17.5 Retrieval and access logging

Create an FTS5 external-content index over active/validated memory title andcontent. Retrieval applies:

Project and global visibility filter.

Lifecycle and target filter.

FTS relevance.

Confidence, evidence quality, recency, and observed usefulness.

Contradiction penalty and bounded linked-memory expansion.

Context-pack token budget.

Every candidate returned to a context pack creates a memory_access row withrun, task, session, memory, query digest, rank, score, selected flag, estimatedtokens, and later used/helpful/harmful feedback. Store the retrievalalgorithm version so evaluations remain interpretable.

18. Retrospective and worth contract

The retrospective capability connects read-only to allow-listed views using aSQLite URI such as file:...?...mode=ro and enables PRAGMA query_only = ON.It must not have a general write connection. Candidate creation and feedback gothrough typed commands that validate scope, provenance, and evidence.

Stable views include:

v_run_summary

v_task_acceptance_evidence

v_token_usage_by_role

v_token_usage_by_model

v_delivery_current_head

v_memory_retrieval_outcomes

v_procedure_effectiveness

v_project_active_memories

v_unresolved_review_findings

v_retention_candidates

“Worth” is a report, not a mutable scalar. It includes:

Dimension

Example observable measure

Outcome

acceptance criteria met, merge status, rollback count

Quality

review severity, regressions, post-merge fixes

Efficiency

tokens, micro-cost, duration, tool calls

Reuse

later retrievals and procedure uses

Helpfulness

improvement relative to comparable tasks without the memory

Harm

failures, contradictions, or extra fixes after retrieval

Evidence strength

independent runs, distinct projects, reproducibility

Comparisons must name their cohort and method. If no credible baseline exists,report descriptive metrics and uncertainty rather than a causal claim.

19. Common-action harnesses

Provide small standard-library scripts behind a single command surface. Theexact packaging may be python -m agentmaster ... or a repository script, butthe release bundle must expose these commands consistently:

agentmaster ledger init|migrate|backup|doctor|stats
agentmaster ledger record-run|record-evidence|record-feedback
agentmaster ledger query runs|tokens|cost|memories|procedures|delivery|entrypoints
agentmaster memory search|show|link|validate|activate|supersede|reject
agentmaster context build --project ... --task ... --budget-tokens ...
agentmaster retro run|show|propose
agentmaster worth run|memory|procedure
agentmaster delivery prepare-pr|watch-ci|review-gate|merge-gate
agentmaster migrate legacy-files

Harness rules:

Machine-readable JSON is the stable interface; concise text is the humandefault.

Mutations support --dry-run and return nonzero on rejected transitions.

delivery review-gate verifies PR head SHA, CI head SHA, reviewed SHA,verdict, unresolved findings, and branch protection status.

delivery merge-gate repeats the checks immediately before merge.

doctor reports SQLite runtime/version, journaling decision, integrity check,pending migrations, orphaned artifacts, permission issues, and stale runningattempts. It does not repair without an explicit option.

record-feedback writes a FEEDBACK row (§17.2): user_session_id and run_idare required, task_id and memory_id are optional, and rating is the tri-stateinteger described in §17.2. It is invoked by the feedback-capture flow attachedat RetrospectivePending→Complete (§9.1).

query entrypoints [--json] lists ENTRYPOINT rows (§17.1) with kind, name,source_path, and active, matching the sub-verb form of the other queryactions.

context build emits the bounded context pack and records retrieval choices.

Scripts are invokable by skills and agents without parsing human prose.

20. Skill routing and delivery contracts

20.1 writing-skills

Create a dedicated writing-skills skill for tasks that create or materiallychange SKILL.md, agent descriptions, frontmatter, invocation examples, or skilltests. Plans declare it with a structured Uses: field. The orchestrator mustinclude the skill's checklist and relevant target schema in the context pack.

The capability must check:

trigger description and non-trigger boundaries;

supported tools and least authority;

model/effort frontmatter validity per target;

explicit handoff and output schema;

idempotent/recoverable behavior;

stop conditions and failure semantics;

examples and tests for invocation, not just prose quality;

generated parity and documentation updates.

This is task-scoped expertise, not permission to install or modify unrelatedskills. Changes to the writing-skills capability itself require independentreview and procedure-version evaluation.

20.2 Git publisher

Create a coordinator-owned git-publisher agent with only the permissions neededfor the selected delivery mode. It receives an approved publication manifest:

repository and expected clean/dirty paths;

base branch and required base SHA;

feature branch and allowed commits;

explicit paths to stage;

conventional commit message;

PR base/title/body/template evidence;

required checks and reviewer route;

merge strategy and branch-deletion policy.

It must refuse to:

stage unexpected paths;

rewrite history or force-push;

publish secrets or ignored runtime state;

merge a head different from the reviewed and green SHA;

mark a review successful on behalf of the reviewer;

bypass branch protection or required checks.

The publisher records every git/GitHub action and resulting SHA/URL in theledger. A retry reconciles existing branch, PR, checks, and review before acting.

20.3 Deterministic review invocation

agentmaster-execute must transition from CI_PENDING to REVIEW_REQUIREDonly when all required checks are successful for the current PR head. Theorchestrator then dispatches the configured reviewer with an immutable reviewpacket.

The reviewer returns a machine-readable result:

{
  "schema_version": 1,
  "reviewed_sha": "<40-hex commit>",
  "verdict": "GOOD | NEEDS_FIXES",
  "findings": [],
  "evidence_gaps": [],
  "summary": "..."
}

Acceptance rules:

GOOD is valid only when reviewed_sha equals PR head and CI head.

NEEDS_FIXES moves accepted findings into task work and invalidates all priorgreen/review gates when a new commit is pushed.

A malformed result is a failed review, never GOOD.

The reviewer may report an out-of-scope concern separately; it cannot silentlyexpand the implementation task.

A stop hook blocks successful execution termination while the state isREVIEW_REQUIRED, REVIEWING, FIXES_REQUIRED, MERGE_PENDING, orRETROSPECTIVE_PENDING for the selected delivery mode.

The stop hook reports the next required action and is idempotent. It must notrecursively relaunch after a configured retry ceiling.

20.4 Recursive improvement

The improvement loop is:

Record structured execution and evidence.

Complete an outcome-aware retrospective.

Propose candidate memories or procedure changes.

Validate on an independent run, test fixture, or human review.

Activate at project scope.

Observe later retrieval and procedure-use outcomes.

Promote, supersede, demote, or reject with evidence.

A procedure proposal creates a new inactive PROCEDURE_VERSION; it never editsthe active skill in place. Adoption requires a normal branch, tests, CI,independent review, and merge. The ledger informs code changes but cannot makethem by itself.

21. Pytest, type, and readability contract

Configure pytest in pyproject.toml:

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = ["--strict-config", "--strict-markers", "-ra"]
xfail_strict = true
filterwarnings = ["error"]
markers = [
  "subprocess: spawns a local child process",
  "integration: crosses a CLI and installer/filesystem boundary",
  "sqlite: exercises a real SQLite database",
]

Testing rules:

Mark subprocess modules/tests consistently. Reserve integration for trueboundary-crossing behavior; tmp_path alone does not make a test integration.

The sqlite marker identifies real database tests but may overlap unit orintegration classification. Quality slices must be non-overlapping.

Move CLI subprocess behavior out of parity tests. Parity verifies canonicalsource/generated equivalence only.

Parametrize model, effort, percentage, malformed payload, target/flag, statetransition, migration, scope, and retrieval matrices with descriptive IDs.

Type shared fixtures and factories. Subprocess helpers returnsubprocess.CompletedProcess[str].

Every subprocess uses an argument list, finite timeout, check=False, capturedtext, and no shell=True.

Build test environments from a scrubbed baseline, including Claude, Copilot,Agentmaster home, ledger, compaction, debug, GitHub, and token variables.

Replace sleeps and timestamp assumptions with injected clocks, unique-nameproviders, synchronization primitives, or deterministic fake providers.

Do not mock SQLite internals. Use temporary real databases for migrations,constraints, transactions, views, FTS, backup, and concurrency tests.

Add corruption, busy-timeout, WAL-fallback, interrupted migration, andread-only retrospective tests.

Avoid autouse unless it enforces a true suite-wide invariant.

Intentional warnings use narrow pytest.warns; xfails require a linked issue.

Assert public behavior and durable state, not private call order unless orderis the safety property.

Quality slices:

uv run pytest -m "not subprocess and not integration"
uv run pytest -m "subprocess and not integration"
uv run pytest -m integration
uv run pytest

Ruff uses line length 90, target py314, complexity 10, production ANN, blindexception, unused-argument, branch/return/argument/statement, and nesting checks.Use narrow test exceptions for conventional pytest signatures. Do not suppresscomplexity in installer transactions, ledger migrations, ownership, deliverygates, or memory promotion.

22. Standard workflow for every micro-PR

Tasks below are sequential, not stacked. The next branch starts only after thepreceding PR is merged into develop.

22.1 Start

git switch develop
git pull --ff-only origin develop
git status --short
git switch -c <branch-name>

The worktree must be clean. Never branch from another feature branch. Record thebase SHA in the run ledger once that capability exists.

22.2 Implement and verify

Run focused tests while iterating. Before each task's final implementationcommit, run:

python install.py sync
bash scripts/code-quality.sh all
git diff --check

Inspect generated changes. Do not stage unrelated user files.

22.3 Commit and push logical boundaries

git add <explicit-paths>
git diff --cached --check
git commit -m "<conventional commit>"
git push -u origin <branch-name>

Push after every logical commit. Never force-push.

22.4 Open PR and watch current-head CI

agentmaster delivery prepare-pr --template .github/PULL_REQUEST_TEMPLATE.md
gh pr create --base develop --head <branch-name> \
  --title "<conventional title>" --body-file <completed-template>
agentmaster delivery watch-ci --pr <number>

Before the delivery harness exists, use gh pr checks --watch and record the PRhead SHA manually. The PR states scope, non-goals, acceptance evidence, tests,generated files, migrations, settings behavior, rollback, docs, and manualverification.

22.5 Independent Agentmaster review

Only after CI is green on the latest commit:

/agentmaster-review Review the current PR against origin/develop. Verify every
acceptance criterion, installer and migration safety, ledger invariants,
generated parity, tests, documentation, and delivery evidence. Return a
machine-readable GOOD or NEEDS_FIXES verdict for the exact PR head SHA.

For early PRs before the deterministic review work lands, record the verdictand reviewed SHA in the PR template. After it lands, use:

agentmaster delivery review-gate --pr <number>

If NEEDS_FIXES:

Accept or reject each finding with rationale.

Fix accepted findings on the same branch.

Commit review fixes separately and push immediately.

Wait for CI on the new head.

Invoke a fresh independent review for the new head.

22.6 Merge

agentmaster delivery merge-gate --pr <number>
gh pr merge <number> --merge --delete-branch
git switch develop
git pull --ff-only origin develop

Before the merge harness exists, manually prove current PR head equals green CIhead and reviewed SHA. Never bypass checks, self-declare GOOD, or merge a stalereviewed commit.

23. Microtask sequence

Each microtask names the expected branch and commit. If a task requires a secondlogical commit, its message is listed explicitly and both commits are pushedseparately.

Microtask 1 — Python 3.14 cleanup

Branch: refactor/python-314-cleanup

Commit: refactor: modernize runtime code for Python 3.14

Scope: install.py, installer/*.py, scripts/telemetry_report.py, Ruffconfiguration, and directly affected tests.

Work:

Remove all from __future__ import annotations, the manualsys.version_info guard, and unnecessary TYPE_CHECKING scaffolding.

Set Ruff target to py314.

Replace bare collections with precise built-in generics and introduce onlysmall useful PEP 695 aliases.

Tighten narration-only docstrings/comments while retaining safety,ownership, and provider-difference explanations.

Preserve behavior and runtime dependency count exactly.

Focused verification:

rg -n '^from __future__|sys\.version_info|TYPE_CHECKING' --glob '*.py'
uv run ruff check . --no-fix
uv run ty check
uv run pytest tests/test_actions.py tests/test_claude_target.py \
  tests/test_copilot_target.py tests/test_telemetry_report.py

Acceptance: the search is empty, public CLI behavior is unchanged, no runtimedependency is added, and the full gate passes.

Microtask 2 — Installer configuration domain and CLI separation

Branch: refactor/installer-configuration

Commit: refactor: separate installer configuration from CLI parsing

Scope: install.py, new installer/config.py, new tests/test_cli.py, paritytests, and shared fixtures.

Work:

Add typed slotted records for unresolved and resolved configuration.

Use StrEnum or literal validation for targets, roles, effort, delivery,capture, and redaction modes.

Move defaults, model/percentage/path validation, precedence, TTY resolution,and summary rendering into pure functions.

Keep argparse.Namespace in the CLI boundary.

Split CLI subprocess coverage from parity coverage.

Remove the misleading validate --target surface or retain only amigration error that explains whole-tree validation.

Add --config, --agentmaster-home, --no-input, and deterministic TOMLloading without implementing target mutations yet.

Print the resolved plan before writes.

Focused verification:

uv run pytest tests/test_cli.py tests/test_parity.py
uv run ty check
python install.py install --target claude --dry-run --no-input \
  --claude-dir "$(mktemp -d)"

Acceptance: resolution is filesystem-independent, noninteractive runs neverprompt, unknown/invalid TOML fields identify their path, and current defaultinstalls remain compatible.

Microtask 3 — Strict frontmatter rendering

Branch: refactor/frontmatter-overrides

Commit: refactor: centralize agent frontmatter overrides

Scope: new installer/frontmatter.py, renderer and target modules, newtests/test_frontmatter.py, and affected rendering tests.

Work:

Implement the bounded allow-list updater in Section 13.

Replace Claude and Copilot model-replacement implementations.

Let render_worker receive role-specific scalar overrides without mutatingthe frozen manifest.

Preserve deterministic sync output.

Focused verification:

uv run pytest tests/test_frontmatter.py tests/test_parity.py \
  tests/test_claude_target.py tests/test_copilot_target.py
python install.py sync
python install.py validate

Acceptance: malformed or duplicate frontmatter fails before writes, Markdownbodies are byte-preserved, and no global regex can rewrite body content.

Microtask 4 — Configurable runtime roles

Branch: feat/runtime-role-configuration

Commit: feat: configure Agentmaster runtime roles

Scope: installer CLI/config, manifest, renderer, Claude/Copilot targets,orchestrator/implementer/reviewer/git-publisher sources and generated files,README files, and CLI/target/parity tests.

Work:

Add all role model/effort flags from Section 11.

Add interactive prompts with concise quality/cost tradeoffs.

Add effort: medium to canonical Claude implementer frontmatter.

Add explicit Claude defaults for orchestrator, reviewer, and git publisher.

Keep coordinator and role choices independent.

Remove --model; make its error name replacement flags.

Reject provider-invalid option combinations before writes.

Never emit a Copilot effort field.

Document default, budget-oriented, and explicitly pinned examples.

Focused verification:

tmp="$(mktemp -d)"
python install.py install --target claude --no-input --claude-dir "$tmp" \
  --claude-implementer-model sonnet --claude-implementer-effort high \
  --claude-review-model opus --claude-review-effort high
rg -n '^model:|^effort:' "$tmp/agents"
uv run pytest tests/test_cli.py tests/test_frontmatter.py \
  tests/test_claude_target.py tests/test_copilot_target.py tests/test_parity.py

Acceptance: every supported role resolves independently, defaults match thecontract, Copilot contains no unsupported effort, and install-time overrides donot change committed defaults.

Microtask 5 — Transactional file actions

Branch: fix/transactional-installer-actions

Commit: fix: make installer batches rollback safely

Scope: installer/actions.py, action tests, and affected targets.

Work:

Make backup directories collision-safe.

Preserve destination permissions unless an explicit mode is planned.

Track created, updated, removed, and mode-changed paths.

Restore the entire batch on a first, middle, or final write failure.

Retain diagnostics and report original and rollback failures separately.

Use injected writers/unique-name providers rather than permission or timingtricks in tests.

Ensure dry-run creates nothing.

Focused verification:

uv run pytest tests/test_actions.py
uv run ty check

Acceptance: simulated failures restore the exact prior destination state,backup paths cannot collide, and executable semantics remain correct.

Microtask 6 — Transactional Agentmaster and Claude settings

Branch: refactor/managed-settings-plan

Commit: refactor: plan managed settings transactionally

Scope: new installer/managed_state.py, installer/agentmaster_config.py,installer/claude_settings.py, Claude target, actions only where a generic planprimitive is necessary, and focused tests.

Work:

Parse and validate Agentmaster TOML and Claude JSON with pure functions.

Deeply validate mutable JSON shapes: root, hooks, event arrays, hook entries,and env.

Represent complete settings/config/owned-state outputs as normal file plansin the same batch as agents and hooks.

Preserve unknown TOML keys and unrelated JSON keys.

Version owned state and store only values needed for conditional restore.

Plan uninstall validation/restoration before deletions.

Make dry-run report create/update/skip/remove accurately.

Focused verification:

uv run pytest tests/test_agentmaster_config.py tests/test_claude_settings.py \
  tests/test_claude_target.py tests/test_actions.py

Acceptance: no target mutates settings outside the plan, later user editssurvive uninstall, malformed settings fail before removal, and formatting maynormalize without losing semantic data.

Microtask 7 — Ledger-aware installer planning

Branch: feat/ledger-installation-options

Commit: feat: configure Agentmaster ledger installation

Scope: installer CLI/config/plans, Agentmaster config, docs, and tests. This taskplans only paths and bootstrap intent; schema implementation follows later.

Work:

Add --ledger-path, --no-ledger, --artifact-dir, and--delivery-mode.

Default to structured ledger metadata with failures-only raw capture andstandard redaction.

Include ledger/artifact initialization in summary and dry-run.

Enforce permissions and target/flag conflicts in the plan model.

Add an idempotent bootstrap placeholder that refuses an unknown newer schemarather than creating an incompatible database.

Focused verification:

uv run pytest tests/test_cli.py tests/test_agentmaster_config.py \
  tests/test_install_plans.py

Acceptance: dry-run creates nothing, disabled ledger creates nothing, resolvedpaths are unambiguous, and install remains standard-library-only.

Microtask 8 — Safe Claude auto-compaction

Branch: feat/claude-auto-compaction

Commit: feat: configure Claude auto-compaction safely

Scope: CLI/config, Claude target/settings, README, and focused tests.

Work:

Implement the percentage and clear options and interactive choices fromSection 15.

Manage the environment value through owned state in the normal transaction.

Preserve the original pre-Agentmaster value across reinstalls.

Use exact session-wide wording in summary and documentation.

Reject percentages outside 1..100 and invalid target combinations.

Focused verification:

tmp="$(mktemp -d)"
python install.py install --target claude --no-input --claude-dir "$tmp" \
  --auto-compact-percent 50
uv run python -c 'import json,pathlib,sys; print(json.loads(pathlib.Path(sys.argv[1]).read_text())["env"]["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"])' \
  "$tmp/settings.json"
uv run pytest tests/test_cli.py tests/test_claude_settings.py \
  tests/test_claude_target.py

Acceptance: explicit 50 writes string "50"; omission preserves behavior;clear/uninstall restore only owned state; Copilot rejects Claude-only flags.

Microtask 9 — Collision-safe compaction observability

Branch: fix/compaction-observability

Commit: fix: make compaction snapshots observable and collision-safe

Scope: precompact hook, hook helpers, legacy telemetry report, hook/report tests,and README.

Work:

Create one unique sortable snapshot directory per compaction.

Defensively extract agent type, trigger, threshold, pre/post token values,and provider session identifiers from supported payload shapes.

Preserve five-column legacy telemetry compatibility usingprecompact:<agent-type> and the token column.

Distinguish main session, implementer, and other subagents.

Keep optional-payload failures fail-open and preserve redacted debug support.

Add deterministic same-time/two-process collision tests.

Focused verification:

uv run pytest tests/test_hooks.py tests/test_hooklib.py \
  tests/test_telemetry_report.py

Acceptance: parallel snapshots never merge or overwrite, old rows remainreadable, and telemetry can identify which agent compacted and at what tokencount when the provider supplies it.

Microtask 10 — Pytest discipline and readability gates

Branch: test/pytest-quality-standards

Commits, pushed separately:

test: enforce strict pytest practices

style: enforce readable Python constraints

Scope: pyproject.toml, Ruff config, shared fixtures, CLI/hook/telemetry tests,other tests only where isolation requires it, production readability findings,quality script, and contributor docs.

Work for commit 1:

Apply the pytest contract in Section 21.

Mark subprocess, integration, and SQLite tests consistently.

Parametrize repeated matrices with descriptive IDs.

Type fixtures/factories and enforce finite subprocess timeouts.

Scrub Claude, Copilot, Agentmaster, GitHub, token, and debug environment.

Replace all timing luck and sleeps with deterministic collaborators.

Add non-overlapping marker slices to the quality script.

Work for commit 2:

Enforce py314, line length 90, complexity 10, production annotations,blind-exception, unused-argument, excessive-structure, and nesting checks.

Refactor findings into typed domain functions; do not blanket-suppress.

Keep ty authoritative and avoid Any-based escapes.

Do not add mandatory docstring rules or a coverage target.

Focused verification:

uv run pytest --collect-only
uv run pytest -m "not subprocess and not integration"
uv run pytest -m "subprocess and not integration"
uv run pytest -m integration
uv run pytest
uv run ruff check .
uv run ty check
bash scripts/code-quality.sh all

Acceptance: unknown markers/config, warnings, and unexpected xpasses fail;slices collect intended tests; environments are isolated; no wall-clock luckremains; production code meets the documented readability constraints.

Microtask 11 — Ledger foundation and migrations

Branch: feat/ledger-foundation

Commits, pushed separately:

feat: add versioned SQLite ledger

test: verify ledger recovery and compatibility

Scope: new agentmaster/ledger/ package or equivalently named runtime package,schema migration resources, CLI bootstrap integration, and focused tests.

Work:

Add standard-library connection factory, migration runner, schema metadata,health record, transactions, and SQLite backup API wrapper.

Implement local-filesystem and SQLite-version journaling selection, includingWAL safety gate and recorded fallback reason.

Enable foreign keys and finite busy timeout on every connection.

Create paths/modes safely and refuse newer unknown schema versions.

Back up before migrations that transform existing data.

Test clean initialize, repeated initialize, ordered migration, failedmigration rollback, corrupt database, read-only access, permissions, busyretry ceiling, WAL selection, and DELETE fallback.

Add ledger init, migrate, backup, and doctor commands.

Focused verification:

uv run pytest -m sqlite tests/test_ledger_connection.py \
  tests/test_ledger_migrations.py tests/test_ledger_backup.py
uv run ty check

Acceptance: schema changes are atomic and versioned, backup is consistent,unsafe WAL is not selected, runtime dependencies remain empty, and doctor givesactionable diagnostics without mutating by default.

Microtask 12 — Execution and token accounting schema

Branch: feat/execution-ledger

Commit: feat: record runs agents tools and model usage

Scope: ledger migrations/models/queries, recording harnesses, provider adapters,and tests.

Work:

Add PROJECT, RUN, TASK, TASK_DEPENDENCY, AGENT_SESSION,MODEL_CALL, TOOL_CALL, and COMPACTION_EVENT tables with constraints andindexes from Section 17.

Normalize project identity while retaining root aliases for moved checkouts.

Record exact provider usage fields when present and nullable fields when not.

Store provider usage JSON only after redaction.

Store pricing source/version and integer micro-cost; if pricing is absent,keep cost null.

Add run/task/model/role aggregate views and JSON query output.

Make append operations idempotent on provider/event identifiers.

Focused verification:

uv run pytest -m sqlite tests/test_ledger_execution.py \
  tests/test_token_accounting.py tests/test_project_identity.py

Acceptance: token dimensions remain distinct, missing usage is not fabricated,duplicate delivery cannot double-count calls, and every aggregate is traceableto source rows.

Microtask 13 — Artifact and evidence provenance

Branch: feat/evidence-ledger

Commit: feat: persist content-addressed execution evidence

Scope: artifact store, evidence schema/migration, redaction/digest code,acceptance evidence mapper, harness commands, and tests.

Work:

Add content-addressed SHA-256 artifact storage and atomic deduplicated writes.

Add ARTIFACT and EVIDENCE tables and task-criterion links.

Record command, exit status, commit SHA, artifact digest, media type, size,retention class, and redaction state.

Apply standard redaction before persistence; never hash a secret merely toclaim it is safe to store.

Detect missing/orphaned/mismatched artifacts in doctor.

Add retention marking and explicit purge with dry-run.

Produce the task acceptance-evidence view.

Focused verification:

uv run pytest -m sqlite tests/test_artifact_store.py \
  tests/test_evidence_ledger.py tests/test_redaction.py

Acceptance: identical safe content deduplicates, a write crash leaves no partialartifact, evidence binds to criterion and SHA, secrets in fixtures are redacted,and expired content removal preserves provenance metadata.

Microtask 14 — Project-scoped linked memory

Branch: feat/project-memory-ledger

Commits, pushed separately:

feat: add scoped evidence-backed memories

feat: add deterministic memory retrieval

Scope: memory schema/migrations, FTS5, domain services, retrieval, CLI, and tests.

Work for commit 1:

Add MEMORY, MEMORY_SCOPE, MEMORY_TARGET, MEMORY_LINK, andMEMORY_EVIDENCE with lifecycle constraints.

Separate origin project from visibility scope.

Implement candidate, validate, activate, supersede, reject, and archivetransitions with provenance checks.

Enforce project/global promotion rules and counterevidence.

Work for commit 2:

Add external-content FTS5 index and deterministic synchronization.

Implement project/global filters, target matching, scoring, contradictionpenalty, two-hop traversal, and context token ceiling.

Add memory_access logging for shown/selected/used/helpful/harmful outcomes.

Add search/show/link/transition commands with JSON output.

Focused verification:

uv run pytest -m sqlite tests/test_memory_schema.py \
  tests/test_memory_lifecycle.py tests/test_memory_retrieval.py

Acceptance: no cross-project leakage, global memory is explicitly validated,links are bounded and auditable, supersession preserves history, and everyretrieval pack records why each memory appeared.

Microtask 15 — Procedures, retrospectives, and evaluations

Branch: feat/retrospective-ledger

Commit: feat: evaluate retrospectives memories and procedures

Scope: procedure/retro/evaluation migrations and services, read-only views,retrospective integration, worth reports, and tests.

Work:

Add RETROSPECTIVE, RETRO_OBSERVATION, PROCEDURE,PROCEDURE_VERSION, PROCEDURE_USE, EVALUATION, andEVALUATION_METRIC.

Provide the stable views in Section 18.

Give retrospective code a read-only, query-only connection to allow-listedviews and no arbitrary write handle.

Add validated commands for candidates, evidence links, and feedback.

Implement descriptive worth reports with named cohorts/methods and explicituncertainty.

Prevent a new procedure version from becoming active without normal deliverygates.

Focused verification:

uv run pytest -m sqlite tests/test_retrospective_ledger.py \
  tests/test_readonly_views.py tests/test_worth_reports.py \
  tests/test_procedure_versions.py

Acceptance: retrospective SQL cannot write, candidates are evidence-linked,worth never implies unsupported causality, and procedure history is immutable.

Microtask 16 — Ledger harness and context builder

Branch: feat/ledger-harness

Commit: feat: add Agentmaster ledger and context commands

Scope: unified command entry point, commands in Section 19, context packs,documentation, shell quality, and subprocess/integration tests.

Work:

Expose all implemented ledger, memory, retro, worth, and context commandswith stable JSON schemas and concise text output.

Generate role-specific context packs with token estimates, selected memories,procedures, evidence requirements, budget, and stop conditions.

Record memory retrieval and pack digest.

Add finite-timeout scripts for common operations; avoid duplicating policy inshell and Python.

Document backup/restore, local-filesystem requirement, privacy, retention,and failure recovery.

Focused verification:

uv run pytest tests/test_ledger_cli.py tests/test_context_builder.py \
  -m "subprocess or integration"
python -m agentmaster ledger doctor --json

Acceptance: skills can invoke machine-readable commands without scraping prose,context packs are bounded and project-filtered, and every mutating commandsupports dry-run where meaningful.

Microtask 17 — Hook ingestion and legacy migration

Branch: feat/ledger-event-ingestion

Commits, pushed separately:

feat: record hook events in the ledger

feat: import legacy Agentmaster history

Scope: hooks, event normalization/spool, compaction integration, legacy importer,docs, and tests.

Work for commit 1:

Normalize supported hook payloads into append-only ledger events and typedtables.

Keep hooks fail-open. If the ledger is busy/unavailable, atomically spool aredacted event for later bounded ingestion.

Add idempotency keys so replay cannot duplicate tokens or compactions.

Link compaction snapshots to artifact and agent-session records.

Work for commit 2:

Add dry-run and explicit apply import for legacy telemetry, evidence,retrospectives, and recognized ledger.sqlite.db.

Preserve original files and create import provenance/digests.

Report skipped, ambiguous, redacted, and malformed records.

Focused verification:

uv run pytest tests/test_hook_ledger.py tests/test_event_spool.py \
  tests/test_legacy_migration.py -m "sqlite or subprocess or integration"

Acceptance: hooks never block Claude on optional observability failure, replayis idempotent, token rows are not double-counted, and migration deletes nothing.

Microtask 18 — writing-skills capability

Branch: feat/writing-skills-capability

Commit: feat: add task-scoped skill authoring guidance

Scope: canonical skill source, manifest/generated target files, plan schema/parser,examples, parity tests, and skill invocation tests.

Work:

Implement the writing-skills contract in Section 20.1.

Add structured plan metadata such as Uses: writing-skills with strictvalidation and unknown-capability errors.

Route only tasks that create or materially change skills/agent definitions.

Include target-specific frontmatter and tool-authority checks.

Test triggering, non-triggering, generated parity, and invalid plan metadata.

Focused verification:

uv run pytest tests/test_plan_parser.py tests/test_skill_routing.py \
  tests/test_parity.py
python install.py sync
python install.py validate

Acceptance: skill work receives the capability deterministically, unrelatedwork does not, target schemas are validated, and source/generated files agree.

Microtask 19 — Orchestrator state machine and recovery

Branch: feat/orchestrator-control-plane

Commits, pushed separately:

feat: add durable orchestration state machine

feat: resume interrupted Agentmaster runs

Scope: canonical agentmaster-execute source, orchestrator agent, plan/taskschema, ledger run/task transitions, generated targets, and tests.

Work for commit 1:

Replace the mechanical-dispatch-only contract with Section 9's activecontrol-plane responsibilities while preserving the rule that it does notimplement repository changes.

Implement typed, validated state transitions and append-only transitionevents.

Add preflight for repository, worktree, base SHA, configuration, tools,dependencies, ledger health, delivery authority, and budgets.

Track task readiness, running leases, blocked reasons, required evidence,and selected delivery mode.

Prevent invalid completion transitions.

Work for commit 2:

Reconcile stale running leases, git branch/head, PR, CI, review, and mergestate after interruption.

Make dispatch and transition operations idempotent.

Require user direction when external state conflicts cannot be resolvedsafely.

Record recovery decisions and evidence.

Focused verification:

uv run pytest tests/test_orchestrator_state.py \
  tests/test_orchestrator_preflight.py tests/test_orchestrator_recovery.py
python install.py sync
python install.py validate

Acceptance: illegal transitions fail closed, an interrupted run resumes withoutduplicate dispatch/publication, and execute cannot finish before its configuredterminal gates.

Microtask 20 — Risk routing, context budgets, and scout policy

Branch: feat/orchestrator-routing

Commit: feat: route Agentmaster work by risk and evidence

Scope: orchestrator routing, context builder integration, task schema, agentprompts, ledger evaluations, docs, and tests.

Work:

Add deterministic risk factors for destructive state, migration, auth,concurrency, release, schema, public API, and large change surface.

Route high-risk or ambiguous questions to coordinator-owned scouts orstronger review; route routine bounded implementation to the configuredimplementer.

Keep implementer scout spawning disabled by default. If experimental enableis present, cap it to one read-only scout with a separate budget and report.

Enforce per-run/per-task token, cost, duration, parallelism, and context-packbudgets without silently changing acceptance criteria.

Generate context packs and record selected memories/procedures.

Require evidence sufficiency before delivery.

Add deterministic fixtures comparing routing outcomes and budget exhaustion.

Focused verification:

uv run pytest tests/test_risk_routing.py tests/test_budget_policy.py \
  tests/test_context_builder.py tests/test_evidence_sufficiency.py

Acceptance: scouts are used only for bounded independent work, implementerfan-out is off by default, hard-budget exhaustion stops dispatch with a clearreason, and no memory leaks across projects.

Microtask 21 — Deterministic independent review gate

Branch: feat/deterministic-agentmaster-review

Commits, pushed separately:

feat: add structured independent Agentmaster review

feat: enforce review completion before execute stops

Scope: reviewer agent/skill, execute/orchestrator skill, hook configuration,review schema/ledger integration, generated targets, and tests.

Work for commit 1:

Define immutable review packet and structured response from Section 20.3.

Route review to configured reviewer model/effort and a session independentfrom implementation.

Store review, findings, evidence gaps, and reviewed SHA.

Validate verdict enum, SHA, finding shape, and reviewer identity.

Work for commit 2:

Add a stop hook/state guard that blocks successful execute termination untilthe required current-head review is complete.

Convert NEEDS_FIXES findings into explicit accepted/rejected work items.

Invalidate review and CI gates on any new head SHA.

Cap retry loops and surface unresolved blockers to the user.

Test missing, malformed, stale, NEEDS_FIXES, corrected, and GOOD paths.

Focused verification:

uv run pytest tests/test_review_schema.py tests/test_review_gate.py \
  tests/test_execute_stop_hook.py tests/test_orchestrator_state.py
python install.py sync
python install.py validate

Acceptance: a prompt cannot impersonate a completed review, GOOD is tied tothe exact head, a new commit invalidates it, and execute cannot silently endwith review pending.

Microtask 22 — Git publisher and current-head delivery gates

Branch: feat/git-publisher-delivery

Commits, pushed separately:

feat: add bounded git publisher agent

feat: verify PR CI review and merge head

Scope: git-publisher agent/skill, delivery harness commands, ledger deliverytables/views, PR-template validator, workflow watcher, generated targets, andtests using local git fixtures/fake GitHub responses.

Work for commit 1:

Implement the publication manifest and refusal rules in Section 20.2.

Add intentional staging, commit, push, and PR-creation commands.

Validate required PR-template sections and evidence links before create.

Reconcile an existing branch/PR on retry.

Work for commit 2:

Add prepare-pr, watch-ci, review-gate, and merge-gate commands.

Persist delivery attempts, CI checks, review SHA, and merge status.

Require PR head = CI head = reviewed SHA immediately before merge.

Reject pending, skipped-required, cancelled, stale, or ambiguous checks.

Use finite polling with progress updates and cancellation handling.

Test no-force-push, unexpected paths, stale review, head advance duringpolling, failed checks, retry, and already-merged reconciliation.

Focused verification:

uv run pytest tests/test_git_publisher.py tests/test_delivery_cli.py \
  tests/test_delivery_gate.py -m "subprocess or integration or sqlite"
python install.py sync
python install.py validate

Acceptance: implementers cannot publish, the publisher cannot stage outside itsmanifest, automation never merges a stale head, and retries do not duplicate PRs.

Microtask 23 — Recursive-improvement policy and evaluation loop

Branch: feat/recursive-improvement-loop

Commit: feat: validate Agentmaster learning proposals

Scope: retrospective and memory/procedure policy, evaluation jobs/harnesses,orchestrator end-of-run phase, docs, and tests.

Work:

Run retrospective after the configured delivery terminal state and beforerun completion.

Create candidates, counterfactuals, evidence links, and proposed scope.

Schedule or describe independent validation; never self-activate from theproposing session.

Calculate descriptive worth dimensions and later retrieval/procedureoutcomes.

Enforce project activation and cross-project global promotion thresholds.

Turn procedure adoption into a normal code/skill PR with writing-skills,CI, review, and merge gates.

Add demotion/supersession paths for harmful or stale knowledge.

Test confirmation-bias cases: repeated same-session evidence, correlatedruns, contradictory evidence, and superficially cheaper but lower-qualityoutcomes.

Focused verification:

uv run pytest tests/test_improvement_policy.py tests/test_memory_promotion.py \
  tests/test_procedure_evaluation.py tests/test_worth_reports.py

Acceptance: the system can learn recursively but cannot silently rewrite orglobally promote itself; every promotion is reproducible from independentevidence and an explicit approval transition.

Microtask 24 — Repository quality, CI, and contributor UX

Branch: chore/repository-quality

Commits, pushed separately:

chore: tighten repository hygiene

ci: harden quality and release workflows

Scope: .gitignore, PR template, quality/release workflows, quality script,Makefile, README, release builder/manifest/check tests, and migration/recoverydocumentation.

Work for commit 1:

Replace the generic .gitignore with repository-specific Python/uv, test,build, editor, transcript, worktree, Agentmaster runtime, SQLite journal/WAL,backup, spool, and artifact rules. Do not ignore migration sources or fixturedatabases intentionally committed for tests.

Add PR template sections for scope, non-goals, criteria/evidence, generatedfiles, schema/settings migration, rollback, tests, manual checks, token/costeffect, reviewed SHA, and verdict.

Align Makefile and README with final CLI/harness commands.

Remove stale counts and claims.

Work for commit 2:

Use uv sync --locked everywhere.

Add least-privilege permissions, timeouts, and concurrency cancellation.

Run the authoritative quality script including marker slices, migrationtests, generated parity, and release bundle smoke tests.

Centralize release bundle membership in a tested source of truth.

Require runtime modules, migrations, agents, skills, hooks, and scripts;exclude tests, caches, local ledgers, artifacts, WAL/SHM files, backups,worktrees, and session data.

Smoke-test install --help, ledger doctor --help, and a temporary ledgerinitialize from the extracted archive under Python 3.14.

Produce SHA256SUMS for all release assets.

Document that published tags are immutable; a bad release gets a new patch.

Focused verification:

bash scripts/code-quality.sh all
make help
python install.py --help
python -m agentmaster ledger doctor --help

Acceptance: workflows are lockfile-deterministic and least-privilege, PRs carrycurrent-head evidence, archives contain the complete runtime but no user state,and checksum generation is tested before tagging.

Microtask 25 — v1 migration, documentation, and release preparation

Branch: release/v2.0.0

Commits, pushed separately:

docs: add Agentmaster v2 migration and operations guide

chore(release): prepare v2.0.0

Start only after Microtasks 1–24 are merged into develop and develop CI isgreen.

Scope: version/lock, README and operations/migration docs, release notes,installer migration messaging, archive manifest, and final smoke tests.

Work for commit 1:

Document v1-to-v2 installer changes, removal of --model, role defaults,config precedence, ledger privacy/retention, local-filesystem constraint,backup/restore, legacy import, delivery modes, budgets, review gate, androllback.

Provide explicit examples for default, budget-oriented, no-ledger, 50%compaction, project memory query, retrospective, PR delivery, and recovery.

Add a migration rehearsal fixture covering existing Claude/Copilot settings,user edits, telemetry/evidence/retro files, and uninstall.

Include known limitations: provider usage may be unavailable; monetary costdepends on pricing provenance; embeddings are not included; implementerscouts are off by default.

Work for commit 2:

Set the version using uv:

uv version 2.0.0
uv lock

Run full quality, migration rehearsal, release build, manifest inspection,extracted-archive smoke tests, integrity check, and checksum verification.

Commit and push; open a PR to develop; pass current-head CI and independentAgentmaster review; merge through the standard workflow.

Focused verification:

bash scripts/code-quality.sh all
python -m agentmaster migrate legacy-files --dry-run --project .
python -m agentmaster ledger doctor --json
<repository release-builder command>
sha256sum --check SHA256SUMS

Acceptance: pyproject.toml and uv.lock report 2.0.0; migration preserves alluser-owned state; release archive/install/ledger smoke tests pass; release-prepPR is green and GOOD for its exact head.

Microtask T11 — Session-scoped repo workspace

Branch: fix/session-scoped-workspace

Scope: repo-local session directory keying, USER_SESSION correlation(harness_session_id, §17.1).

Work: key repo-local session directories by harness_session_id; every hookpayload's session_id field is that harness id. Full task detail lives in thev2 execution plan.

Microtask T19 — Entrypoint registry

Branch: feat/entrypoint-registry

Scope: ENTRYPOINT table population (§17.1), CLI registered command table,agentmaster ledger query entrypoints (§19).

Work: seed skill/agent/hook ENTRYPOINT rows from the installer manifest;seed command rows from the CLI's own registered command table. Full taskdetail lives in the v2 execution plan.

Microtask T26 — Feedback capture loop

Branch: feat/feedback-capture-loop

Scope: FEEDBACK table (§17.2), agentmaster ledger record-feedback (§19),RetrospectivePending→Complete capture attachment (§9.1).

Work: implement the feedback capture flow and its FEEDBACK writes; wirememory-candidate creation to consume FEEDBACK per §17.2/§17.4. Full taskdetail lives in the v2 execution plan.

24. Final integration: develop to main

After the release-preparation PR merges:

git switch develop
git pull --ff-only origin develop
bash scripts/code-quality.sh all
git fetch origin
git log --oneline origin/main..origin/develop
git diff --check origin/main...origin/develop

Open the release PR using the final publisher/harness:

agentmaster delivery prepare-pr --base main --head develop \
  --template .github/PULL_REQUEST_TEMPLATE.md
gh pr create --base main --head develop \
  --title "release: agentmaster v2.0.0" \
  --body-file <completed-release-template>
agentmaster delivery watch-ci --pr <release-pr-number>

When current-head CI is green, invoke:

/agentmaster-review Review origin/main...origin/develop as the v2.0.0 release
candidate. Verify v1 migration, installer ownership and rollback, role routing,
orchestration state/recovery, current-head delivery gates, project memory
isolation, ledger migrations and privacy, token accounting, recursive-improvement
safeguards, generated parity, archive contents, checksums, documentation, and the
complete test gate. Return GOOD or NEEDS_FIXES for the exact develop head SHA.

Then require:

agentmaster delivery review-gate --pr <release-pr-number>
agentmaster delivery merge-gate --pr <release-pr-number>
gh pr merge <release-pr-number> --merge

If fixes are required, create a fresh micro-branch from develop, merge its PRthrough the normal process, refresh the release PR, and repeat CI/review. Do notcommit release fixes directly to develop or main.

25. Tag and publish

Tag the exact reviewed merge commit on main:

git switch main
git pull --ff-only origin main
test "$(uv run python -c "import pathlib,tomllib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])")" = "2.0.0"
bash scripts/code-quality.sh all
git tag -a v2.0.0 -m "agentmaster v2.0.0"
git push origin v2.0.0

Monitor and verify:

gh run list --workflow release.yml --limit 1
gh run watch <run-id> --exit-status
gh release view v2.0.0

release_dir="$(mktemp -d)"
gh release download v2.0.0 --dir "$release_dir"
cd "$release_dir"
sha256sum --check SHA256SUMS
unzip -l agentmaster-v2.0.0.zip

Extract the archive into a new temporary directory under Python 3.14 and verify:

python install.py install --help
python -m agentmaster ledger init --path ./test-ledger.sqlite3
python -m agentmaster ledger doctor --path ./test-ledger.sqlite3 --json
python install.py install --target claude --no-input --dry-run \
  --claude-dir ./test-claude --agentmaster-home ./test-agentmaster

Release acceptance:

GitHub Release v2.0.0 exists and the tag points to the reviewed main merge.

The release workflow is green.

Zip and SHA256SUMS are attached and verify.

Archive contains installer, runtime package, migrations, manifest, agents,skills, hooks, and required scripts.

Archive excludes tests, caches, worktrees, user config, databases, WAL/SHMfiles, backups, artifacts, spools, telemetry, evidence, and sessions.

Installer and ledger commands work from the extracted archive on Python 3.14.

If the tag workflow fails before publishing, fix through develop → reviewedPR → main and use the next valid version as appropriate. Never move or reuse atag after a GitHub Release has been published.

26. Final acceptance checklist

Installer and configuration

No from __future__ imports or pre-3.14 guards remain.

Runtime dependencies remain empty.

Claude coordinator, orchestrator, implementer, reviewer, and git-publishermodel configuration works.

Supported Claude role effort is configurable; implementer defaults tomedium.

Copilot coordinator and implementer models are configurable and nounsupported effort field is emitted.

Removed --model fails with an actionable v2 migration message.

Resolved configuration is displayed before writes; --no-input neverprompts.

50% auto-compaction is opt-in and documented as main-session/subagent-wide.

Dry-run reports all settings, config, owned-state, ledger, and directorymutations without writing.

Mid-batch failure restores prior state and retains diagnostics.

Uninstall restores only owned values; later user edits survive.

Backups and compaction snapshots cannot collide.

Orchestration and delivery

Orchestrator performs preflight, state management, routing, budgets,evidence checks, delivery, review, and retrospective orchestration.

Orchestrator never edits repository source or self-approves.

Implementer scout spawning is disabled by default.

Coordinator-owned scouts are bounded, read-only, and used only when theirindependence/cost benefit is explicit.

Context packs are project-filtered, token-bounded, and retrieval-audited.

writing-skills is invoked for skill/agent authoring tasks.

Git publisher stages only approved paths and never force-pushes.

PR preparation validates the evidence template.

CI watcher uses finite polling and reports the exact head.

A valid GOOD review is independent and tied to the exact PR head.

New commits invalidate prior CI/review approval.

Execute cannot finish while required delivery, review, merge, or retrogates remain pending.

Recovery reconciles interrupted state idempotently.

Repo-local session directories are keyed by harness_session_id; every hookpayload's session_id field is that harness id (T11).

Ledger, memory, and recursive improvement

Default ledger is ~/.agentmaster/ledger.sqlite3, configurable/disableable,with directory 0700 and database/backup 0600.

Foreign keys, busy timeout, journaling safety gate, backup API, and schemaversioning are enforced.

Local-filesystem limitation and WAL fallback are documented/tested.

Project identity supports moved roots without cross-project leakage.

Runs, tasks, sessions, model/tool calls, compactions, delivery, checks,reviews, evidence, retrospectives, memories, procedures, and evaluations arequeryable.

Input, output, reasoning, cache-read, cache-write, billed, and contexttokens remain distinct and nullable.

Costs use integer micro-units with pricing provenance; unavailable cost isnot reported as zero.

Raw outputs are failure-only by default, redacted, content-addressed, andretention-controlled.

Memories separate origin project from visibility scope and can be linked,targeted, superseded, contradicted, and evidenced.

FTS5 retrieval applies project/state/target filters and bounded link depth.

Every retrieval records rank, score, token estimate, selection, use, andoutcome feedback.

Retrospective reads only allow-listed query-only views.

Retrospectives create candidates, never active/global knowledge directly.

Global promotion requires independent evidence from multiple projects andapproval.

Procedure changes create reviewed versions through the normal PR workflow.

“Worth” reports multidimensional evidence and uncertainty, not a subjectivescalar.

Legacy telemetry/evidence/retro import is dry-runnable, idempotent, andnon-destructive.

ENTRYPOINT rows seed from the installer manifest (skill/agent/hook) and theCLI's registered command table (command); entrypoint_id on AGENT_SESSION andTOOL_CALL is nullable and queryable via agentmaster ledger query entrypoints(T19).

FEEDBACK rows enforce the tri-state rating check constraint, requireuser_session_id and run_id, allow nullable task_id/memory_id, and arewritten by record-feedback and the RetrospectivePending→Complete capture flow(T26).

Quality and release

Generated Claude/Copilot files pass parity validation.

CLI tests are separate from parity tests.

Pytest rejects unknown config/markers, warnings, and unexpected xpasses.

Unit, subprocess, integration, and SQLite selections are intentional andpass.

Test subprocesses have finite timeouts and scrubbed environments.

Migration, corruption, busy, rollback, concurrency, privacy, recovery,stale-SHA, and promotion regressions are covered deterministically.

Ruff enforces Python 3.14 annotations and readability constraints.

Ruff, bashate, ty, compileall, pytest, migration checks, archive tests, andparity validation pass through one quality command.

CI uses uv sync --locked, least privilege, timeouts, and concurrencycancellation.

Every micro-PR started from current develop; every logical commit waspushed immediately.

Every PR passed current-head CI and independent Agentmaster review beforemerge.

The develop → main release PR passed the same gates.

v2.0.0 assets, contents, smoke tests, and checksums are verified.

27. Definition of success

Agentmaster v2.0.0 is successful when it is safer and more useful over repeatedprojects without becoming self-authorizing. The installer makes behavior andcost choices explicit; the orchestrator remains actively responsible frompreflight through retrospective; delivery cannot skip current-head review; andthe ledger can explain what happened, what it cost, what evidence supports amemory, where that memory applies, and whether using it improved later work.

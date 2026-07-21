"""Ledger schema version and migration metadata (SPEC.md §16.3, §16.4).

Table DDL for later migrations lives with the migration that introduces it,
not here; this module only holds the version number this package understands
and the ordered list of migrations that reach it.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class Migration:
    """One forward-only schema step and the version it produces."""

    to_version: int
    description: str
    apply: Callable[[sqlite3.Connection], None]


def _create_ledger_health(connection: sqlite3.Connection) -> None:
    """Add the singleton table `doctor`/`connect` use to report journaling decisions."""
    connection.execute(
        'CREATE TABLE ledger_health ('
        'id INTEGER PRIMARY KEY CHECK (id = 1), '
        'journal_mode TEXT NOT NULL, '
        'journal_mode_reason TEXT NOT NULL, '
        'sqlite_version TEXT NOT NULL, '
        'checked_at TEXT NOT NULL'
        ')'
    )


_EVIDENCE_KINDS = (
    'test-result',
    'command-result',
    'diff-inspection',
    'generated-parity-check',
    'artifact-hash',
    'ci-check',
    'reviewer-finding',
)  # SPEC.md line 394
_RUN_STATES = (
    'Planned',
    'Preflight',
    'Executing',
    'Verifying',
    'FixesRequired',
    'DeliveryPending',
    'CIPending',
    'ReviewRequired',
    'Reviewing',
    'MergePending',
    'Merged',
    'RetrospectivePending',
    'Complete',
    'Blocked',
    'Failed',
    'Cancelled',
)  # SPEC.md §9.1 run state machine
_TASK_STATES = ('ready', 'running', 'blocked', 'failed', 'review-required', 'complete')
_DELIVERY_MODES = ('local', 'commit', 'pull-request', 'merge')  # SPEC.md §9.2
_ENTRYPOINT_KINDS = ('skill', 'agent', 'hook', 'command')


def _in_clause(values: tuple[str, ...]) -> str:
    return ', '.join(f"'{value}'" for value in values)


def _create_user_session(connection: sqlite3.Connection) -> None:
    """USER_SESSION: the Agentmaster-generated session, correlated to the harness."""
    connection.execute(
        'CREATE TABLE USER_SESSION ('
        'user_session_id TEXT PRIMARY KEY, '
        'harness_session_id TEXT NOT NULL, '
        'created_at TEXT NOT NULL'
        ')'
    )
    connection.execute(
        'CREATE INDEX idx_user_session_harness_session_id '
        'ON USER_SESSION(harness_session_id)'
    )


def _create_entrypoint(connection: sqlite3.Connection) -> None:
    """ENTRYPOINT: the skill/agent/hook/command that originated work; seeded later."""
    connection.execute(
        'CREATE TABLE ENTRYPOINT ('
        'id TEXT PRIMARY KEY, '
        f'kind TEXT NOT NULL CHECK (kind IN ({_in_clause(_ENTRYPOINT_KINDS)})), '
        'name TEXT NOT NULL, '
        'source_path TEXT, '
        'active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)), '
        'created_at TEXT NOT NULL'
        ')'
    )
    connection.execute(
        'CREATE INDEX idx_entrypoint_kind_active ON ENTRYPOINT(kind, active)'
    )


def _create_project(connection: sqlite3.Connection) -> None:
    """PROJECT: normalized project identity (canonical root, remote, fingerprint)."""
    connection.execute(
        'CREATE TABLE PROJECT ('
        'id TEXT PRIMARY KEY, '
        'canonical_root TEXT NOT NULL, '
        'remote_identity TEXT, '
        'display_name TEXT, '
        'fingerprint TEXT NOT NULL UNIQUE, '
        'created_at TEXT NOT NULL, '
        'last_seen_at TEXT NOT NULL'
        ')'
    )


def _create_run(connection: sqlite3.Connection) -> None:
    """RUN: one orchestrated attempt, owned by a project and initiated by its session."""
    delivery_mode_check = f'CHECK (delivery_mode IN ({_in_clause(_DELIVERY_MODES)}))'
    state_check = f'CHECK (state IN ({_in_clause(_RUN_STATES)}))'
    connection.execute(
        'CREATE TABLE RUN ('
        'id TEXT PRIMARY KEY, '
        'project_id TEXT NOT NULL REFERENCES PROJECT(id), '
        'user_session_id TEXT NOT NULL REFERENCES USER_SESSION(user_session_id), '
        'parent_run_id TEXT REFERENCES RUN(id), '
        'plan_id TEXT, '
        f'delivery_mode TEXT NOT NULL {delivery_mode_check}, '
        f'state TEXT NOT NULL {state_check}, '
        'base_sha TEXT, '
        'head_sha TEXT, '
        'started_at TEXT NOT NULL, '
        'ended_at TEXT, '
        'duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0)'
        ')'
    )
    connection.execute('CREATE INDEX idx_run_project_id ON RUN(project_id)')
    connection.execute('CREATE INDEX idx_run_user_session_id ON RUN(user_session_id)')
    connection.execute('CREATE INDEX idx_run_parent_run_id ON RUN(parent_run_id)')
    connection.execute('CREATE INDEX idx_run_state ON RUN(state)')
    connection.execute('CREATE INDEX idx_run_started_at ON RUN(started_at)')


def _create_task(connection: sqlite3.Connection) -> None:
    """TASK: one unit of work within a run's task graph (§9, §17.1)."""
    connection.execute(
        'CREATE TABLE TASK ('
        'id TEXT PRIMARY KEY, '
        'run_id TEXT NOT NULL REFERENCES RUN(id), '
        'parent_task_id TEXT REFERENCES TASK(id), '
        'title TEXT NOT NULL, '
        f'state TEXT NOT NULL CHECK (state IN ({_in_clause(_TASK_STATES)})), '
        'risk_level TEXT, '
        'sequence_no INTEGER NOT NULL, '
        'acceptance_json TEXT, '
        'started_at TEXT, '
        'ended_at TEXT'
        ')'
    )
    connection.execute('CREATE INDEX idx_task_run_id ON TASK(run_id)')
    connection.execute('CREATE INDEX idx_task_parent_task_id ON TASK(parent_task_id)')
    connection.execute('CREATE INDEX idx_task_state ON TASK(state)')
    connection.execute('CREATE INDEX idx_task_started_at ON TASK(started_at)')


def _create_task_dependency(connection: sqlite3.Connection) -> None:
    """TASK_DEPENDENCY: a task's ordering/blocking dependency on another task (§17.1)."""
    connection.execute(
        'CREATE TABLE TASK_DEPENDENCY ('
        'task_id TEXT NOT NULL REFERENCES TASK(id), '
        'depends_on_task_id TEXT NOT NULL REFERENCES TASK(id), '
        'dependency_kind TEXT NOT NULL, '
        'PRIMARY KEY (task_id, depends_on_task_id)'
        ')'
    )
    connection.execute(
        'CREATE INDEX idx_task_dependency_task_id ON TASK_DEPENDENCY(task_id)'
    )
    connection.execute(
        'CREATE INDEX idx_task_dependency_depends_on_task_id '
        'ON TASK_DEPENDENCY(depends_on_task_id)'
    )


def _create_agent_session(connection: sqlite3.Connection) -> None:
    """AGENT_SESSION: one dispatched agent's session, optionally scoped to a task."""
    connection.execute(
        'CREATE TABLE AGENT_SESSION ('
        'id TEXT PRIMARY KEY, '
        'run_id TEXT NOT NULL REFERENCES RUN(id), '
        'task_id TEXT REFERENCES TASK(id), '
        'parent_session_id TEXT REFERENCES AGENT_SESSION(id), '
        'entrypoint_id TEXT REFERENCES ENTRYPOINT(id), '
        'role TEXT NOT NULL, '
        'provider TEXT NOT NULL, '
        'model TEXT NOT NULL, '
        'effort TEXT, '
        'state TEXT NOT NULL, '
        'context_limit_tokens INTEGER '
        'CHECK (context_limit_tokens IS NULL OR context_limit_tokens >= 0), '
        'started_at TEXT NOT NULL, '
        'ended_at TEXT'
        ')'
    )
    connection.execute('CREATE INDEX idx_agent_session_run_id ON AGENT_SESSION(run_id)')
    connection.execute('CREATE INDEX idx_agent_session_task_id ON AGENT_SESSION(task_id)')
    connection.execute(
        'CREATE INDEX idx_agent_session_parent_session_id '
        'ON AGENT_SESSION(parent_session_id)'
    )
    connection.execute(
        'CREATE INDEX idx_agent_session_entrypoint_id ON AGENT_SESSION(entrypoint_id)'
    )


def _create_model_call(connection: sqlite3.Connection) -> None:
    """MODEL_CALL: one append-only provider call and its token/cost accounting (§17.1).

    `provider_call_id` is unique per agent session when present, so replayed
    delivery of the same provider event cannot double-count tokens or cost.
    """
    connection.execute(
        'CREATE TABLE MODEL_CALL ('
        'id TEXT PRIMARY KEY, '
        'agent_session_id TEXT NOT NULL REFERENCES AGENT_SESSION(id), '
        'provider_call_id TEXT, '
        'model TEXT NOT NULL, '
        'effort TEXT, '
        'input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0), '
        'output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0), '
        'reasoning_tokens INTEGER '
        'CHECK (reasoning_tokens IS NULL OR reasoning_tokens >= 0), '
        'cache_read_tokens INTEGER '
        'CHECK (cache_read_tokens IS NULL OR cache_read_tokens >= 0), '
        'cache_write_tokens INTEGER '
        'CHECK (cache_write_tokens IS NULL OR cache_write_tokens >= 0), '
        'billed_tokens INTEGER CHECK (billed_tokens IS NULL OR billed_tokens >= 0), '
        'context_estimate_tokens INTEGER '
        'CHECK (context_estimate_tokens IS NULL OR context_estimate_tokens >= 0), '
        'duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0), '
        'cost_micro_usd INTEGER CHECK (cost_micro_usd IS NULL OR cost_micro_usd >= 0), '
        'pricing_source TEXT, '
        'stop_reason TEXT, '
        'provider_usage_json TEXT, '
        'created_at TEXT NOT NULL'
        ')'
    )
    connection.execute(
        'CREATE INDEX idx_model_call_agent_session_id ON MODEL_CALL(agent_session_id)'
    )
    connection.execute(
        'CREATE UNIQUE INDEX ux_model_call_agent_session_provider_call '
        'ON MODEL_CALL(agent_session_id, provider_call_id) '
        'WHERE provider_call_id IS NOT NULL'
    )


def _create_tool_call(connection: sqlite3.Connection) -> None:
    """TOOL_CALL: one tool invocation within an agent session (§17.1)."""
    connection.execute(
        'CREATE TABLE TOOL_CALL ('
        'id TEXT PRIMARY KEY, '
        'agent_session_id TEXT NOT NULL REFERENCES AGENT_SESSION(id), '
        'task_id TEXT REFERENCES TASK(id), '
        'entrypoint_id TEXT REFERENCES ENTRYPOINT(id), '
        'tool_name TEXT NOT NULL, '
        'operation TEXT, '
        'state TEXT NOT NULL, '
        'duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0), '
        'exit_code INTEGER, '
        'input_digest TEXT, '
        'output_digest TEXT, '
        'created_at TEXT NOT NULL'
        ')'
    )
    connection.execute(
        'CREATE INDEX idx_tool_call_agent_session_id ON TOOL_CALL(agent_session_id)'
    )
    connection.execute('CREATE INDEX idx_tool_call_task_id ON TOOL_CALL(task_id)')
    connection.execute(
        'CREATE INDEX idx_tool_call_entrypoint_id ON TOOL_CALL(entrypoint_id)'
    )


def _create_compaction_event(connection: sqlite3.Connection) -> None:
    """COMPACTION_EVENT: one context-compaction event within an agent session (§17.1).

    `snapshot_artifact_id` is a plain identifier column, not a FK, because the
    ARTIFACT table it will reference does not exist until Microtask 13 adds
    it; SQLite refuses even a NULL insert against a FK naming a nonexistent
    table. The named index required by §16.4 is still added now.
    """
    connection.execute(
        'CREATE TABLE COMPACTION_EVENT ('
        'id TEXT PRIMARY KEY, '
        'agent_session_id TEXT NOT NULL REFERENCES AGENT_SESSION(id), '
        'trigger TEXT NOT NULL, '
        'threshold_percent INTEGER '
        'CHECK (threshold_percent IS NULL OR threshold_percent BETWEEN 0 AND 100), '
        'pre_tokens INTEGER CHECK (pre_tokens IS NULL OR pre_tokens >= 0), '
        'post_tokens INTEGER CHECK (post_tokens IS NULL OR post_tokens >= 0), '
        'snapshot_artifact_id TEXT, '
        'created_at TEXT NOT NULL'
        ')'
    )
    connection.execute(
        'CREATE INDEX idx_compaction_event_agent_session_id '
        'ON COMPACTION_EVENT(agent_session_id)'
    )
    connection.execute(
        'CREATE INDEX idx_compaction_event_snapshot_artifact_id '
        'ON COMPACTION_EVENT(snapshot_artifact_id)'
    )


def _create_artifact(connection: sqlite3.Connection) -> None:
    """ARTIFACT: one content-addressed blob owned by a project (§17.2)."""
    connection.execute(
        'CREATE TABLE ARTIFACT ('
        'id TEXT PRIMARY KEY, '
        'project_id TEXT NOT NULL REFERENCES PROJECT(id), '
        'sha256 TEXT NOT NULL, '
        'media_type TEXT NOT NULL, '
        'byte_size INTEGER NOT NULL CHECK (byte_size >= 0), '
        'relative_path TEXT NOT NULL, '
        'retention_class TEXT NOT NULL, '
        'redaction_state TEXT NOT NULL, '
        'created_at TEXT NOT NULL, '
        'expires_at TEXT'
        ')'
    )
    connection.execute('CREATE INDEX idx_artifact_project_id ON ARTIFACT(project_id)')


def _create_evidence(connection: sqlite3.Connection) -> None:
    """EVIDENCE: one acceptance-evidence record binding an artifact to a task (§17.2)."""
    evidence_kind_check = f'CHECK (evidence_kind IN ({_in_clause(_EVIDENCE_KINDS)}))'
    connection.execute(
        'CREATE TABLE EVIDENCE ('
        'id TEXT PRIMARY KEY, '
        'run_id TEXT NOT NULL REFERENCES RUN(id), '
        'task_id TEXT REFERENCES TASK(id), '
        'artifact_id TEXT NOT NULL REFERENCES ARTIFACT(id), '
        f'evidence_kind TEXT NOT NULL {evidence_kind_check}, '
        'criterion_id TEXT, '
        'command TEXT, '
        'exit_code INTEGER, '
        'commit_sha TEXT, '
        'summary TEXT, '
        'created_at TEXT NOT NULL'
        ')'
    )
    connection.execute('CREATE INDEX idx_evidence_run_id ON EVIDENCE(run_id)')
    connection.execute('CREATE INDEX idx_evidence_task_id ON EVIDENCE(task_id)')
    connection.execute('CREATE INDEX idx_evidence_artifact_id ON EVIDENCE(artifact_id)')


def _rebuild_compaction_event_with_artifact_fk(connection: sqlite3.Connection) -> None:
    """Rebuild COMPACTION_EVENT so `snapshot_artifact_id` gains a real FK to ARTIFACT.

    Microtask 12 could not declare this FK because SQLite refuses to create a
    table with a foreign key naming a table that does not exist yet, and
    ARTIFACT is only added by this migration. This follows SQLite's table-
    rebuild pattern (create new, copy, drop, rename, recreate indices).
    COMPACTION_EVENT is only ever a foreign-key *child* (nothing else
    references it), so the rebuild is safe with `PRAGMA foreign_keys = ON`
    held throughout: SQLite only refuses to drop a table that is itself the
    *parent* of a still-enforced foreign key.
    """
    connection.execute(
        'CREATE TABLE COMPACTION_EVENT_NEW ('
        'id TEXT PRIMARY KEY, '
        'agent_session_id TEXT NOT NULL REFERENCES AGENT_SESSION(id), '
        'trigger TEXT NOT NULL, '
        'threshold_percent INTEGER '
        'CHECK (threshold_percent IS NULL OR threshold_percent BETWEEN 0 AND 100), '
        'pre_tokens INTEGER CHECK (pre_tokens IS NULL OR pre_tokens >= 0), '
        'post_tokens INTEGER CHECK (post_tokens IS NULL OR post_tokens >= 0), '
        'snapshot_artifact_id TEXT REFERENCES ARTIFACT(id), '
        'created_at TEXT NOT NULL'
        ')'
    )
    connection.execute(
        'INSERT INTO COMPACTION_EVENT_NEW '
        '(id, agent_session_id, trigger, threshold_percent, '
        'pre_tokens, post_tokens, snapshot_artifact_id, created_at) '
        'SELECT id, agent_session_id, trigger, threshold_percent, '
        'pre_tokens, post_tokens, snapshot_artifact_id, created_at '
        'FROM COMPACTION_EVENT'
    )
    connection.execute('DROP TABLE COMPACTION_EVENT')
    connection.execute('ALTER TABLE COMPACTION_EVENT_NEW RENAME TO COMPACTION_EVENT')
    connection.execute(
        'CREATE INDEX idx_compaction_event_agent_session_id '
        'ON COMPACTION_EVENT(agent_session_id)'
    )
    connection.execute(
        'CREATE INDEX idx_compaction_event_snapshot_artifact_id '
        'ON COMPACTION_EVENT(snapshot_artifact_id)'
    )


def _add_evidence_schema(connection: sqlite3.Connection) -> None:
    """Add artifact/evidence provenance schema (SPEC.md §23 Microtask 13, §17.2)."""
    _create_artifact(connection)
    _create_evidence(connection)
    _rebuild_compaction_event_with_artifact_fk(connection)


_MEMORY_STATES = (
    'Candidate',
    'Validated',
    'Active',
    'Superseded',
    'Archived',
    'Rejected',
)  # SPEC.md §17.4 memory lifecycle
_MEMORY_SCOPE_KINDS = ('project', 'project_family', 'global')  # SPEC.md §17.3
_MEMORY_LINK_KINDS = (
    'supports',
    'contradicts',
    'refines',
    'supersedes',
    'derived_from',
    'related',
)  # SPEC.md §17.3


def _create_memory(connection: sqlite3.Connection) -> None:
    """MEMORY: one lifecycle-tracked, evidence-backed unit of knowledge (§17.2)."""
    state_check = f'CHECK (state IN ({_in_clause(_MEMORY_STATES)}))'
    connection.execute(
        'CREATE TABLE MEMORY ('
        'id TEXT PRIMARY KEY, '
        'origin_project_id TEXT NOT NULL REFERENCES PROJECT(id), '
        f'state TEXT NOT NULL {state_check}, '
        'memory_kind TEXT NOT NULL, '
        'title TEXT NOT NULL, '
        'content TEXT NOT NULL, '
        'confidence TEXT, '
        'usefulness_count INTEGER NOT NULL DEFAULT 0 CHECK (usefulness_count >= 0), '
        'harmful_count INTEGER NOT NULL DEFAULT 0 CHECK (harmful_count >= 0), '
        'supersedes_memory_id TEXT REFERENCES MEMORY(id), '
        'created_at TEXT NOT NULL, '
        'updated_at TEXT NOT NULL'
        ')'
    )
    connection.execute(
        'CREATE INDEX idx_memory_origin_project_id ON MEMORY(origin_project_id)'
    )
    connection.execute(
        'CREATE INDEX idx_memory_supersedes_memory_id ON MEMORY(supersedes_memory_id)'
    )


def _create_memory_scope(connection: sqlite3.Connection) -> None:
    """MEMORY_SCOPE: a memory's visibility, independent of where it originated (§17.3).

    The trailing CHECK enforces "a project-scoped row must name a project; a
    global row must not" (§17.3) in SQLite rather than leaving it to callers.
    """
    scope_kind_check = f'CHECK (scope_kind IN ({_in_clause(_MEMORY_SCOPE_KINDS)}))'
    connection.execute(
        'CREATE TABLE MEMORY_SCOPE ('
        'memory_id TEXT NOT NULL REFERENCES MEMORY(id), '
        f'scope_kind TEXT NOT NULL {scope_kind_check}, '
        'project_id TEXT REFERENCES PROJECT(id), '
        'include_descendants TEXT, '
        'created_at TEXT NOT NULL, '
        "CHECK ((scope_kind = 'global') = (project_id IS NULL))"
        ')'
    )
    connection.execute(
        'CREATE INDEX idx_memory_scope_memory_id ON MEMORY_SCOPE(memory_id)'
    )
    connection.execute(
        'CREATE INDEX idx_memory_scope_project_id ON MEMORY_SCOPE(project_id)'
    )


def _create_memory_target(connection: sqlite3.Connection) -> None:
    """MEMORY_TARGET: a skill/agent/tool key a memory applies to (§17.2)."""
    connection.execute(
        'CREATE TABLE MEMORY_TARGET ('
        'memory_id TEXT NOT NULL REFERENCES MEMORY(id), '
        'target_kind TEXT NOT NULL, '
        'target_key TEXT NOT NULL, '
        'created_at TEXT NOT NULL'
        ')'
    )
    connection.execute(
        'CREATE INDEX idx_memory_target_memory_id ON MEMORY_TARGET(memory_id)'
    )


def _create_memory_link(connection: sqlite3.Connection) -> None:
    """MEMORY_LINK: a bounded, typed relation between two memories (§17.3)."""
    link_kind_check = f'CHECK (link_kind IN ({_in_clause(_MEMORY_LINK_KINDS)}))'
    connection.execute(
        'CREATE TABLE MEMORY_LINK ('
        'source_memory_id TEXT NOT NULL REFERENCES MEMORY(id), '
        'target_memory_id TEXT NOT NULL REFERENCES MEMORY(id), '
        f'link_kind TEXT NOT NULL {link_kind_check}, '
        'weight REAL, '
        'created_at TEXT NOT NULL'
        ')'
    )
    connection.execute(
        'CREATE INDEX idx_memory_link_source_memory_id ON MEMORY_LINK(source_memory_id)'
    )
    connection.execute(
        'CREATE INDEX idx_memory_link_target_memory_id ON MEMORY_LINK(target_memory_id)'
    )


def _create_memory_evidence(connection: sqlite3.Connection) -> None:
    """MEMORY_EVIDENCE: the evidence/observation backing one memory (§17.2).

    `observation_id` is a plain identifier column, not a FK, because
    RETRO_OBSERVATION does not exist until Microtask 15 adds it; SQLite
    refuses a FK naming a nonexistent table (same reasoning as
    COMPACTION_EVENT.snapshot_artifact_id in Microtask 12/13 above).
    """
    connection.execute(
        'CREATE TABLE MEMORY_EVIDENCE ('
        'memory_id TEXT NOT NULL REFERENCES MEMORY(id), '
        'evidence_id TEXT NOT NULL REFERENCES EVIDENCE(id), '
        'observation_id TEXT, '
        'relation TEXT NOT NULL, '
        'strength TEXT, '
        'created_at TEXT NOT NULL'
        ')'
    )
    connection.execute(
        'CREATE INDEX idx_memory_evidence_memory_id ON MEMORY_EVIDENCE(memory_id)'
    )
    connection.execute(
        'CREATE INDEX idx_memory_evidence_evidence_id ON MEMORY_EVIDENCE(evidence_id)'
    )
    connection.execute(
        'CREATE INDEX idx_memory_evidence_observation_id '
        'ON MEMORY_EVIDENCE(observation_id)'
    )


def _create_feedback(connection: sqlite3.Connection) -> None:
    """FEEDBACK: a tri-state rating on a run/task/memory (§17.2, amended §17).

    `rating` maps harmful/neutral/helpful onto memory_access's helpful/harmful
    semantics (§16.3). `user_session_id` references USER_SESSION, not
    AGENT_SESSION: feedback is given by the human/harness session, not a
    dispatched agent.
    """
    connection.execute(
        'CREATE TABLE FEEDBACK ('
        'id TEXT PRIMARY KEY, '
        'user_session_id TEXT NOT NULL REFERENCES USER_SESSION(user_session_id), '
        'run_id TEXT NOT NULL REFERENCES RUN(id), '
        'task_id TEXT REFERENCES TASK(id), '
        'memory_id TEXT REFERENCES MEMORY(id), '
        'rating INTEGER NOT NULL CHECK (rating BETWEEN -1 AND 1), '
        'comment TEXT, '
        'created_at TEXT NOT NULL'
        ')'
    )
    connection.execute(
        'CREATE INDEX idx_feedback_user_session_id ON FEEDBACK(user_session_id)'
    )
    connection.execute('CREATE INDEX idx_feedback_run_id ON FEEDBACK(run_id)')
    connection.execute('CREATE INDEX idx_feedback_task_id ON FEEDBACK(task_id)')
    connection.execute('CREATE INDEX idx_feedback_memory_id ON FEEDBACK(memory_id)')


def _add_memory_schema(connection: sqlite3.Connection) -> None:
    """Add scoped, evidence-backed memory schema and FEEDBACK (SPEC.md §23 MT14 c1)."""
    _create_memory(connection)
    _create_memory_scope(connection)
    _create_memory_target(connection)
    _create_memory_link(connection)
    _create_memory_evidence(connection)
    _create_feedback(connection)


_MEMORY_FTS_SYNC_STATES = ('Active', 'Validated')  # SPEC.md §17.5


def _create_memory_fts(connection: sqlite3.Connection) -> None:
    """memory_fts: external-content FTS5 index over active/validated memories (§17.5).

    Triggers keep the index in sync with `MEMORY` (§16.3 sanctions triggers
    only for FTS synchronization): a row is indexed only while its state is
    Active or Validated, so a content edit or a lifecycle transition removes
    the stale entry before (re)inserting the current one.
    """
    connection.execute(
        'CREATE VIRTUAL TABLE memory_fts USING fts5('
        "title, content, content='MEMORY', content_rowid='rowid'"
        ')'
    )
    # `sync_states` interpolates only the hardcoded _MEMORY_FTS_SYNC_STATES
    # tuple, never external input.
    sync_states = _in_clause(_MEMORY_FTS_SYNC_STATES)
    connection.execute(
        'CREATE TRIGGER memory_fts_ai AFTER INSERT ON MEMORY '  # noqa: S608
        f'WHEN new.state IN ({sync_states}) '
        'BEGIN '
        'INSERT INTO memory_fts(rowid, title, content) '
        'VALUES (new.rowid, new.title, new.content); '
        'END'
    )
    connection.execute(
        'CREATE TRIGGER memory_fts_ad AFTER DELETE ON MEMORY '  # noqa: S608
        f'WHEN old.state IN ({sync_states}) '
        'BEGIN '
        'INSERT INTO memory_fts(memory_fts, rowid, title, content) '
        "VALUES ('delete', old.rowid, old.title, old.content); "
        'END'
    )
    connection.execute(
        'CREATE TRIGGER memory_fts_au AFTER UPDATE ON MEMORY '
        'BEGIN '
        'INSERT INTO memory_fts(memory_fts, rowid, title, content) '
        f"SELECT 'delete', old.rowid, old.title, old.content "
        f'WHERE old.state IN ({sync_states}); '
        'INSERT INTO memory_fts(rowid, title, content) '
        f'SELECT new.rowid, new.title, new.content '
        f'WHERE new.state IN ({sync_states}); '
        'END'
    )


def _create_memory_access(connection: sqlite3.Connection) -> None:
    """memory_access: one retrieval-pack row logging why a memory was shown (§17.5)."""
    connection.execute(
        'CREATE TABLE memory_access ('
        'id TEXT PRIMARY KEY, '
        'run_id TEXT NOT NULL REFERENCES RUN(id), '
        'task_id TEXT REFERENCES TASK(id), '
        'agent_session_id TEXT REFERENCES AGENT_SESSION(id), '
        'memory_id TEXT NOT NULL REFERENCES MEMORY(id), '
        'query_digest TEXT NOT NULL, '
        'rank INTEGER NOT NULL CHECK (rank >= 0), '
        'score REAL NOT NULL, '
        'selected INTEGER NOT NULL DEFAULT 0 CHECK (selected IN (0, 1)), '
        'estimated_tokens INTEGER '
        'CHECK (estimated_tokens IS NULL OR estimated_tokens >= 0), '
        'used INTEGER CHECK (used IS NULL OR used IN (0, 1)), '
        'helpful INTEGER CHECK (helpful IS NULL OR helpful IN (0, 1)), '
        'harmful INTEGER CHECK (harmful IS NULL OR harmful IN (0, 1)), '
        'retrieval_algorithm_version TEXT NOT NULL, '
        'created_at TEXT NOT NULL'
        ')'
    )
    connection.execute('CREATE INDEX idx_memory_access_run_id ON memory_access(run_id)')
    connection.execute('CREATE INDEX idx_memory_access_task_id ON memory_access(task_id)')
    connection.execute(
        'CREATE INDEX idx_memory_access_agent_session_id '
        'ON memory_access(agent_session_id)'
    )
    connection.execute(
        'CREATE INDEX idx_memory_access_memory_id ON memory_access(memory_id)'
    )


def _add_memory_retrieval_schema(connection: sqlite3.Connection) -> None:
    """Add the FTS5 retrieval index and access logging (SPEC.md §23 MT14 commit 2)."""
    _create_memory_fts(connection)
    _create_memory_access(connection)


def _add_execution_schema(connection: sqlite3.Connection) -> None:
    """Add the execution/token-accounting tables (SPEC.md §23 Microtask 12, §17.1)."""
    _create_user_session(connection)
    _create_entrypoint(connection)
    _create_project(connection)
    _create_run(connection)
    _create_task(connection)
    _create_task_dependency(connection)
    _create_agent_session(connection)
    _create_model_call(connection)
    _create_tool_call(connection)
    _create_compaction_event(connection)


SUPPORTED_SCHEMA_VERSION = 5

MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        to_version=1, description='add ledger_health table', apply=_create_ledger_health
    ),
    Migration(
        to_version=2,
        description='add execution and token-accounting schema',
        apply=_add_execution_schema,
    ),
    Migration(
        to_version=3,
        description='add artifact and evidence provenance schema',
        apply=_add_evidence_schema,
    ),
    Migration(
        to_version=4,
        description='add scoped evidence-backed memory schema and feedback',
        apply=_add_memory_schema,
    ),
    Migration(
        to_version=5,
        description='add memory FTS5 retrieval index and access logging',
        apply=_add_memory_retrieval_schema,
    ),
)

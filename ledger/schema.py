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


SUPPORTED_SCHEMA_VERSION = 2

MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        to_version=1, description='add ledger_health table', apply=_create_ledger_health
    ),
    Migration(
        to_version=2,
        description='add execution and token-accounting schema',
        apply=_add_execution_schema,
    ),
)

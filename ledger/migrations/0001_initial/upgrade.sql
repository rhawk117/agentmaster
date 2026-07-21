-- Migration 0001_initial: the complete ledger schema (SPEC.md §16, §16.4, §17, §18).
--
-- PRE-RELEASE POLICY: until v2.0.0 ships, agentmaster has no ledger in
-- production use, so schema changes are made by editing this file in place
-- rather than adding a new migration directory. The migration chain only
-- grows once v2.0.0 has released; from then on, this file is frozen and
-- later schema changes add a new `NNNN_name/upgrade.sql`.
--
-- Migrations are forward-only (SPEC.md:55); there is no downgrade.sql. A
-- pre-migration backup (ledger/backup.py) is the rollback mechanism.

-- --- ledger health -----------------------------------------------------
-- Singleton table `doctor`/`connect` use to report journaling decisions.

CREATE TABLE ledger_health (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    journal_mode TEXT NOT NULL,
    journal_mode_reason TEXT NOT NULL,
    sqlite_version TEXT NOT NULL,
    checked_at TEXT NOT NULL
);

-- --- sessions and entrypoints --------------------------------------------

-- USER_SESSION: the Agentmaster-generated session, correlated to the harness.
CREATE TABLE USER_SESSION (
    user_session_id TEXT PRIMARY KEY,
    harness_session_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_user_session_harness_session_id
    ON USER_SESSION(harness_session_id);

-- ENTRYPOINT: the skill/agent/hook/command that originated work; seeded later.
CREATE TABLE ENTRYPOINT (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('skill', 'agent', 'hook', 'command')),
    name TEXT NOT NULL,
    source_path TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE INDEX idx_entrypoint_kind_active ON ENTRYPOINT(kind, active);

-- --- projects, runs, and tasks --------------------------------------------

-- PROJECT: normalized project identity (canonical root, remote, fingerprint).
CREATE TABLE PROJECT (
    id TEXT PRIMARY KEY,
    canonical_root TEXT NOT NULL,
    remote_identity TEXT,
    display_name TEXT,
    fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

-- RUN: one orchestrated attempt, owned by a project and initiated by its session.
CREATE TABLE RUN (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES PROJECT(id),
    user_session_id TEXT NOT NULL REFERENCES USER_SESSION(user_session_id),
    parent_run_id TEXT REFERENCES RUN(id),
    plan_id TEXT,
    delivery_mode TEXT NOT NULL
        CHECK (delivery_mode IN ('local', 'commit', 'pull-request', 'merge')),
    state TEXT NOT NULL CHECK (state IN (
        'Planned', 'Preflight', 'Executing', 'Verifying', 'FixesRequired',
        'DeliveryPending', 'CIPending', 'ReviewRequired', 'Reviewing',
        'MergePending', 'Merged', 'RetrospectivePending', 'Complete',
        'Blocked', 'Failed', 'Cancelled'
    )),
    base_sha TEXT,
    head_sha TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0)
);

CREATE INDEX idx_run_project_id ON RUN(project_id);
CREATE INDEX idx_run_user_session_id ON RUN(user_session_id);
CREATE INDEX idx_run_parent_run_id ON RUN(parent_run_id);
CREATE INDEX idx_run_state ON RUN(state);
CREATE INDEX idx_run_started_at ON RUN(started_at);

-- TASK: one unit of work within a run's task graph (§9, §17.1).
CREATE TABLE TASK (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES RUN(id),
    parent_task_id TEXT REFERENCES TASK(id),
    title TEXT NOT NULL,
    state TEXT NOT NULL
        CHECK (state IN ('ready', 'running', 'blocked', 'failed', 'review-required', 'complete')),
    risk_level TEXT,
    sequence_no INTEGER NOT NULL,
    acceptance_json TEXT,
    started_at TEXT,
    ended_at TEXT
);

CREATE INDEX idx_task_run_id ON TASK(run_id);
CREATE INDEX idx_task_parent_task_id ON TASK(parent_task_id);
CREATE INDEX idx_task_state ON TASK(state);
CREATE INDEX idx_task_started_at ON TASK(started_at);

-- TASK_DEPENDENCY: a task's ordering/blocking dependency on another task (§17.1).
CREATE TABLE TASK_DEPENDENCY (
    task_id TEXT NOT NULL REFERENCES TASK(id),
    depends_on_task_id TEXT NOT NULL REFERENCES TASK(id),
    dependency_kind TEXT NOT NULL,
    PRIMARY KEY (task_id, depends_on_task_id)
);

CREATE INDEX idx_task_dependency_task_id ON TASK_DEPENDENCY(task_id);
CREATE INDEX idx_task_dependency_depends_on_task_id
    ON TASK_DEPENDENCY(depends_on_task_id);

-- --- agent sessions, calls, and events -------------------------------------

-- AGENT_SESSION: one dispatched agent's session, optionally scoped to a task.
CREATE TABLE AGENT_SESSION (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES RUN(id),
    task_id TEXT REFERENCES TASK(id),
    parent_session_id TEXT REFERENCES AGENT_SESSION(id),
    entrypoint_id TEXT REFERENCES ENTRYPOINT(id),
    role TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    effort TEXT,
    state TEXT NOT NULL,
    context_limit_tokens INTEGER
        CHECK (context_limit_tokens IS NULL OR context_limit_tokens >= 0),
    started_at TEXT NOT NULL,
    ended_at TEXT
);

CREATE INDEX idx_agent_session_run_id ON AGENT_SESSION(run_id);
CREATE INDEX idx_agent_session_task_id ON AGENT_SESSION(task_id);
CREATE INDEX idx_agent_session_parent_session_id ON AGENT_SESSION(parent_session_id);
CREATE INDEX idx_agent_session_entrypoint_id ON AGENT_SESSION(entrypoint_id);

-- MODEL_CALL: one append-only provider call and its token/cost accounting (§17.1).
-- `provider_call_id` is unique per agent session when present, so replayed
-- delivery of the same provider event cannot double-count tokens or cost.
CREATE TABLE MODEL_CALL (
    id TEXT PRIMARY KEY,
    agent_session_id TEXT NOT NULL REFERENCES AGENT_SESSION(id),
    provider_call_id TEXT,
    model TEXT NOT NULL,
    effort TEXT,
    input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
    reasoning_tokens INTEGER CHECK (reasoning_tokens IS NULL OR reasoning_tokens >= 0),
    cache_read_tokens INTEGER CHECK (cache_read_tokens IS NULL OR cache_read_tokens >= 0),
    cache_write_tokens INTEGER CHECK (cache_write_tokens IS NULL OR cache_write_tokens >= 0),
    billed_tokens INTEGER CHECK (billed_tokens IS NULL OR billed_tokens >= 0),
    context_estimate_tokens INTEGER
        CHECK (context_estimate_tokens IS NULL OR context_estimate_tokens >= 0),
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    cost_micro_usd INTEGER CHECK (cost_micro_usd IS NULL OR cost_micro_usd >= 0),
    pricing_source TEXT,
    stop_reason TEXT,
    provider_usage_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_model_call_agent_session_id ON MODEL_CALL(agent_session_id);
CREATE UNIQUE INDEX ux_model_call_agent_session_provider_call
    ON MODEL_CALL(agent_session_id, provider_call_id)
    WHERE provider_call_id IS NOT NULL;

-- TOOL_CALL: one tool invocation within an agent session (§17.1).
CREATE TABLE TOOL_CALL (
    id TEXT PRIMARY KEY,
    agent_session_id TEXT NOT NULL REFERENCES AGENT_SESSION(id),
    task_id TEXT REFERENCES TASK(id),
    entrypoint_id TEXT REFERENCES ENTRYPOINT(id),
    tool_name TEXT NOT NULL,
    operation TEXT,
    state TEXT NOT NULL,
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    exit_code INTEGER,
    input_digest TEXT,
    output_digest TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_tool_call_agent_session_id ON TOOL_CALL(agent_session_id);
CREATE INDEX idx_tool_call_task_id ON TOOL_CALL(task_id);
CREATE INDEX idx_tool_call_entrypoint_id ON TOOL_CALL(entrypoint_id);

-- --- artifacts and evidence -------------------------------------------------

-- ARTIFACT: one content-addressed blob owned by a project (§17.2).
CREATE TABLE ARTIFACT (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES PROJECT(id),
    sha256 TEXT NOT NULL,
    media_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    relative_path TEXT NOT NULL,
    retention_class TEXT NOT NULL,
    redaction_state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT
);

CREATE INDEX idx_artifact_project_id ON ARTIFACT(project_id);

-- COMPACTION_EVENT: one context-compaction event within an agent session (§17.1).
-- `snapshot_artifact_id` references ARTIFACT directly: unlike the historical
-- six-step migration chain this collapses, ARTIFACT already exists by the
-- time this table is created, so no later table-rebuild is needed.
CREATE TABLE COMPACTION_EVENT (
    id TEXT PRIMARY KEY,
    agent_session_id TEXT NOT NULL REFERENCES AGENT_SESSION(id),
    trigger TEXT NOT NULL,
    threshold_percent INTEGER
        CHECK (threshold_percent IS NULL OR threshold_percent BETWEEN 0 AND 100),
    pre_tokens INTEGER CHECK (pre_tokens IS NULL OR pre_tokens >= 0),
    post_tokens INTEGER CHECK (post_tokens IS NULL OR post_tokens >= 0),
    snapshot_artifact_id TEXT REFERENCES ARTIFACT(id),
    created_at TEXT NOT NULL
);

CREATE INDEX idx_compaction_event_agent_session_id ON COMPACTION_EVENT(agent_session_id);
CREATE INDEX idx_compaction_event_snapshot_artifact_id
    ON COMPACTION_EVENT(snapshot_artifact_id);

-- EVIDENCE: one acceptance-evidence record binding an artifact to a task (§17.2).
CREATE TABLE EVIDENCE (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES RUN(id),
    task_id TEXT REFERENCES TASK(id),
    artifact_id TEXT NOT NULL REFERENCES ARTIFACT(id),
    evidence_kind TEXT NOT NULL CHECK (evidence_kind IN (
        'test-result', 'command-result', 'diff-inspection',
        'generated-parity-check', 'artifact-hash', 'ci-check', 'reviewer-finding'
    )),
    criterion_id TEXT,
    command TEXT,
    exit_code INTEGER,
    commit_sha TEXT,
    summary TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_evidence_run_id ON EVIDENCE(run_id);
CREATE INDEX idx_evidence_task_id ON EVIDENCE(task_id);
CREATE INDEX idx_evidence_artifact_id ON EVIDENCE(artifact_id);

-- --- retrospectives and observations ----------------------------------------
-- Created ahead of MEMORY_EVIDENCE so RETRO_OBSERVATION already exists for
-- its `observation_id` foreign key (see the same rebuild-avoidance note above).

-- RETROSPECTIVE: the single retrospective a run concludes with (§17.2, §9.1).
-- `run_id` is UNIQUE: the ERD's "RUN ||--o| RETROSPECTIVE" cardinality means a
-- run has at most one retrospective.
CREATE TABLE RETROSPECTIVE (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE REFERENCES RUN(id),
    status TEXT NOT NULL CHECK (status IN ('Pending', 'Complete')),
    outcome TEXT,
    summary TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX idx_retrospective_run_id ON RETROSPECTIVE(run_id);

-- RETRO_OBSERVATION: one claim recorded during a retrospective (§17.2).
CREATE TABLE RETRO_OBSERVATION (
    id TEXT PRIMARY KEY,
    retrospective_id TEXT NOT NULL REFERENCES RETROSPECTIVE(id),
    observation_kind TEXT NOT NULL,
    claim TEXT NOT NULL,
    confidence TEXT,
    counterfactual TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_retro_observation_retrospective_id
    ON RETRO_OBSERVATION(retrospective_id);

-- --- memory ------------------------------------------------------------

-- MEMORY: one lifecycle-tracked, evidence-backed unit of knowledge (§17.2).
-- `proposing_session_id` records which AGENT_SESSION proposed this candidate,
-- so `ledger.memory_service.validate_memory` can enforce §17.4's rule that
-- validating evidence/session must differ from the proposing session.
CREATE TABLE MEMORY (
    id TEXT PRIMARY KEY,
    origin_project_id TEXT NOT NULL REFERENCES PROJECT(id),
    state TEXT NOT NULL CHECK (state IN (
        'Candidate', 'Validated', 'Active', 'Superseded', 'Archived', 'Rejected'
    )),
    memory_kind TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence TEXT,
    usefulness_count INTEGER NOT NULL DEFAULT 0 CHECK (usefulness_count >= 0),
    harmful_count INTEGER NOT NULL DEFAULT 0 CHECK (harmful_count >= 0),
    supersedes_memory_id TEXT REFERENCES MEMORY(id),
    proposing_session_id TEXT REFERENCES AGENT_SESSION(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_memory_origin_project_id ON MEMORY(origin_project_id);
CREATE INDEX idx_memory_supersedes_memory_id ON MEMORY(supersedes_memory_id);
CREATE INDEX idx_memory_proposing_session_id ON MEMORY(proposing_session_id);

-- MEMORY_SCOPE: a memory's visibility, independent of where it originated (§17.3).
-- The trailing CHECK enforces "a project-scoped row must name a project; a
-- global row must not" (§17.3) in SQLite rather than leaving it to callers.
CREATE TABLE MEMORY_SCOPE (
    memory_id TEXT NOT NULL REFERENCES MEMORY(id),
    scope_kind TEXT NOT NULL CHECK (scope_kind IN ('project', 'project_family', 'global')),
    project_id TEXT REFERENCES PROJECT(id),
    include_descendants TEXT,
    created_at TEXT NOT NULL,
    CHECK ((scope_kind = 'global') = (project_id IS NULL))
);

CREATE INDEX idx_memory_scope_memory_id ON MEMORY_SCOPE(memory_id);
CREATE INDEX idx_memory_scope_project_id ON MEMORY_SCOPE(project_id);

-- MEMORY_TARGET: a skill/agent/tool key a memory applies to (§17.2).
CREATE TABLE MEMORY_TARGET (
    memory_id TEXT NOT NULL REFERENCES MEMORY(id),
    target_kind TEXT NOT NULL,
    target_key TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_memory_target_memory_id ON MEMORY_TARGET(memory_id);

-- MEMORY_LINK: a bounded, typed relation between two memories (§17.3).
CREATE TABLE MEMORY_LINK (
    source_memory_id TEXT NOT NULL REFERENCES MEMORY(id),
    target_memory_id TEXT NOT NULL REFERENCES MEMORY(id),
    link_kind TEXT NOT NULL CHECK (link_kind IN (
        'supports', 'contradicts', 'refines', 'supersedes', 'derived_from', 'related'
    )),
    weight REAL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_memory_link_source_memory_id ON MEMORY_LINK(source_memory_id);
CREATE INDEX idx_memory_link_target_memory_id ON MEMORY_LINK(target_memory_id);

-- MEMORY_EVIDENCE: the evidence/observation backing one memory (§17.2).
-- `observation_id` references RETRO_OBSERVATION directly (see the
-- rebuild-avoidance note above RETROSPECTIVE).
CREATE TABLE MEMORY_EVIDENCE (
    memory_id TEXT NOT NULL REFERENCES MEMORY(id),
    evidence_id TEXT NOT NULL REFERENCES EVIDENCE(id),
    observation_id TEXT REFERENCES RETRO_OBSERVATION(id),
    relation TEXT NOT NULL,
    strength TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_memory_evidence_memory_id ON MEMORY_EVIDENCE(memory_id);
CREATE INDEX idx_memory_evidence_evidence_id ON MEMORY_EVIDENCE(evidence_id);
CREATE INDEX idx_memory_evidence_observation_id ON MEMORY_EVIDENCE(observation_id);

-- FEEDBACK: a tri-state rating on a run/task/memory (§17.2, amended §17).
-- `rating` maps harmful/neutral/helpful onto memory_access's helpful/harmful
-- semantics (§16.3). `user_session_id` references USER_SESSION, not
-- AGENT_SESSION: feedback is given by the human/harness session, not a
-- dispatched agent.
CREATE TABLE FEEDBACK (
    id TEXT PRIMARY KEY,
    user_session_id TEXT NOT NULL REFERENCES USER_SESSION(user_session_id),
    run_id TEXT NOT NULL REFERENCES RUN(id),
    task_id TEXT REFERENCES TASK(id),
    memory_id TEXT REFERENCES MEMORY(id),
    rating INTEGER NOT NULL CHECK (rating BETWEEN -1 AND 1),
    comment TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_feedback_user_session_id ON FEEDBACK(user_session_id);
CREATE INDEX idx_feedback_run_id ON FEEDBACK(run_id);
CREATE INDEX idx_feedback_task_id ON FEEDBACK(task_id);
CREATE INDEX idx_feedback_memory_id ON FEEDBACK(memory_id);

-- --- memory retrieval: FTS5 index and access logging (§17.5) ----------------

-- memory_fts: external-content FTS5 index over active/validated memories.
-- Triggers keep the index in sync with `MEMORY` (§16.3 sanctions triggers only
-- for FTS synchronization): a row is indexed only while its state is Active
-- or Validated, so a content edit or a lifecycle transition removes the
-- stale entry before (re)inserting the current one.
CREATE VIRTUAL TABLE memory_fts USING fts5(
    title, content, content='MEMORY', content_rowid='rowid'
);

CREATE TRIGGER memory_fts_ai AFTER INSERT ON MEMORY
WHEN new.state IN ('Active', 'Validated')
BEGIN
    INSERT INTO memory_fts(rowid, title, content)
    VALUES (new.rowid, new.title, new.content);
END;

CREATE TRIGGER memory_fts_ad AFTER DELETE ON MEMORY
WHEN old.state IN ('Active', 'Validated')
BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, title, content)
    VALUES ('delete', old.rowid, old.title, old.content);
END;

CREATE TRIGGER memory_fts_au AFTER UPDATE ON MEMORY
BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, title, content)
    SELECT 'delete', old.rowid, old.title, old.content
    WHERE old.state IN ('Active', 'Validated');
    INSERT INTO memory_fts(rowid, title, content)
    SELECT new.rowid, new.title, new.content
    WHERE new.state IN ('Active', 'Validated');
END;

-- memory_access: one retrieval-pack row logging why a memory was shown (§17.5).
CREATE TABLE memory_access (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES RUN(id),
    task_id TEXT REFERENCES TASK(id),
    agent_session_id TEXT REFERENCES AGENT_SESSION(id),
    memory_id TEXT NOT NULL REFERENCES MEMORY(id),
    query_digest TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK (rank >= 0),
    score REAL NOT NULL,
    selected INTEGER NOT NULL DEFAULT 0 CHECK (selected IN (0, 1)),
    estimated_tokens INTEGER CHECK (estimated_tokens IS NULL OR estimated_tokens >= 0),
    used INTEGER CHECK (used IS NULL OR used IN (0, 1)),
    helpful INTEGER CHECK (helpful IS NULL OR helpful IN (0, 1)),
    harmful INTEGER CHECK (harmful IS NULL OR harmful IN (0, 1)),
    retrieval_algorithm_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_memory_access_run_id ON memory_access(run_id);
CREATE INDEX idx_memory_access_task_id ON memory_access(task_id);
CREATE INDEX idx_memory_access_agent_session_id ON memory_access(agent_session_id);
CREATE INDEX idx_memory_access_memory_id ON memory_access(memory_id);

-- --- procedures, uses, and worth evaluations (§17.2, §18, §20.4) ------------

-- PROCEDURE: a named, project-owned procedure with an independent version history.
CREATE TABLE PROCEDURE (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES PROJECT(id),
    name TEXT NOT NULL,
    scope TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_procedure_project_id ON PROCEDURE(project_id);

-- PROCEDURE_VERSION: one immutable, numbered version of a procedure (§20.4).
-- `status` is `inactive` or `active`: "a new procedure proposal creates a new
-- inactive PROCEDURE_VERSION; it never edits the active skill in place"
-- (§20.4). `UNIQUE(procedure_id, version_no)` keeps that numbered history
-- unambiguous.
CREATE TABLE PROCEDURE_VERSION (
    id TEXT PRIMARY KEY,
    procedure_id TEXT NOT NULL REFERENCES PROCEDURE(id),
    version_no INTEGER NOT NULL CHECK (version_no >= 1),
    content_hash TEXT NOT NULL,
    artifact_id TEXT REFERENCES ARTIFACT(id),
    status TEXT NOT NULL CHECK (status IN ('inactive', 'active')),
    created_at TEXT NOT NULL,
    UNIQUE (procedure_id, version_no)
);

CREATE INDEX idx_procedure_version_procedure_id ON PROCEDURE_VERSION(procedure_id);
CREATE INDEX idx_procedure_version_artifact_id ON PROCEDURE_VERSION(artifact_id);

-- PROCEDURE_USE: one task's application of a procedure version (§17.2).
CREATE TABLE PROCEDURE_USE (
    id TEXT PRIMARY KEY,
    procedure_version_id TEXT NOT NULL REFERENCES PROCEDURE_VERSION(id),
    task_id TEXT REFERENCES TASK(id),
    agent_session_id TEXT REFERENCES AGENT_SESSION(id),
    outcome TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_procedure_use_procedure_version_id
    ON PROCEDURE_USE(procedure_version_id);
CREATE INDEX idx_procedure_use_task_id ON PROCEDURE_USE(task_id);
CREATE INDEX idx_procedure_use_agent_session_id ON PROCEDURE_USE(agent_session_id);

-- EVALUATION: one worth judgment about a memory or a procedure version (§17.2, §18).
-- `evaluator_session_id` references AGENT_SESSION, matching the codebase's
-- existing split between USER_SESSION (the human/harness session that gives
-- FEEDBACK) and AGENT_SESSION (a dispatched session that performs structured
-- analysis, the same role REVIEW.reviewer_session_id plays for code review,
-- §17.1). The trailing CHECK requires every evaluation to evaluate something,
-- matching the ERD's two "evaluates" relationships.
CREATE TABLE EVALUATION (
    id TEXT PRIMARY KEY,
    memory_id TEXT REFERENCES MEMORY(id),
    procedure_version_id TEXT REFERENCES PROCEDURE_VERSION(id),
    project_id TEXT NOT NULL REFERENCES PROJECT(id),
    evaluator_session_id TEXT REFERENCES AGENT_SESSION(id),
    evaluation_kind TEXT NOT NULL,
    decision TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (memory_id IS NOT NULL OR procedure_version_id IS NOT NULL)
);

CREATE INDEX idx_evaluation_memory_id ON EVALUATION(memory_id);
CREATE INDEX idx_evaluation_procedure_version_id ON EVALUATION(procedure_version_id);
CREATE INDEX idx_evaluation_project_id ON EVALUATION(project_id);
CREATE INDEX idx_evaluation_evaluator_session_id ON EVALUATION(evaluator_session_id);

-- EVALUATION_METRIC: one named, unit-carrying measure backing an evaluation (§18).
-- Has no declared primary key, matching MEMORY_SCOPE/MEMORY_TARGET/
-- MEMORY_LINK/MEMORY_EVIDENCE: a plain attribute table keyed by its parent.
CREATE TABLE EVALUATION_METRIC (
    evaluation_id TEXT NOT NULL REFERENCES EVALUATION(id),
    metric_name TEXT NOT NULL,
    value_microunits INTEGER NOT NULL,
    unit TEXT NOT NULL,
    method TEXT NOT NULL
);

CREATE INDEX idx_evaluation_metric_evaluation_id ON EVALUATION_METRIC(evaluation_id);

-- --- stable read-only views (SPEC.md §18) -----------------------------------
-- SQLite rejects writes against a view with no `INSTEAD OF` trigger (none are
-- defined here), which is what makes these safe to expose on a query-only
-- connection. `v_delivery_current_head` and `v_unresolved_review_findings`
-- reference DELIVERY_ATTEMPT, CI_CHECK, REVIEW, and REVIEW_FINDING, which do
-- not exist yet (§17.1); SQLite does not validate a view's table references
-- until it is queried, so these `CREATE VIEW` statements succeed now and
-- those two views only become queryable once those tables are added.

CREATE VIEW v_run_summary AS
SELECT r.id AS run_id, r.project_id, r.user_session_id, r.delivery_mode,
       r.state, r.started_at, r.ended_at, r.duration_ms,
       COUNT(DISTINCT t.id) AS task_count,
       SUM(CASE WHEN t.state = 'complete' THEN 1 ELSE 0 END) AS completed_task_count
FROM RUN r LEFT JOIN TASK t ON t.run_id = r.id
GROUP BY r.id;

CREATE VIEW v_task_acceptance_evidence AS
SELECT t.id AS task_id, t.run_id, t.title, t.state AS task_state,
       t.acceptance_json, e.id AS evidence_id, e.evidence_kind, e.criterion_id,
       e.exit_code, e.commit_sha, e.created_at AS evidence_created_at
FROM TASK t LEFT JOIN EVIDENCE e ON e.task_id = t.id;

CREATE VIEW v_token_usage_by_role AS
SELECT ags.run_id, ags.role, COUNT(mc.id) AS call_count,
       SUM(mc.input_tokens) AS input_tokens, SUM(mc.output_tokens) AS output_tokens,
       SUM(mc.cost_micro_usd) AS cost_micro_usd
FROM AGENT_SESSION ags JOIN MODEL_CALL mc ON mc.agent_session_id = ags.id
GROUP BY ags.run_id, ags.role;

CREATE VIEW v_token_usage_by_model AS
SELECT ags.run_id, mc.model, COUNT(mc.id) AS call_count,
       SUM(mc.input_tokens) AS input_tokens, SUM(mc.output_tokens) AS output_tokens,
       SUM(mc.cost_micro_usd) AS cost_micro_usd
FROM AGENT_SESSION ags JOIN MODEL_CALL mc ON mc.agent_session_id = ags.id
GROUP BY ags.run_id, mc.model;

CREATE VIEW v_delivery_current_head AS
SELECT da.id AS delivery_attempt_id, da.run_id, da.attempt_no, da.branch,
       da.base_sha, da.head_sha, da.pr_number, da.pr_url, da.state AS delivery_state,
       cc.name AS ci_check_name, cc.status AS ci_status, cc.conclusion AS ci_conclusion,
       rv.reviewed_sha, rv.verdict AS review_verdict
FROM DELIVERY_ATTEMPT da
LEFT JOIN CI_CHECK cc ON cc.delivery_attempt_id = da.id AND cc.head_sha = da.head_sha
LEFT JOIN REVIEW rv ON rv.delivery_attempt_id = da.id AND rv.reviewed_sha = da.head_sha;

CREATE VIEW v_memory_retrieval_outcomes AS
SELECT ma.id AS memory_access_id, ma.run_id, ma.task_id, ma.agent_session_id,
       ma.memory_id, m.title, m.state AS memory_state, ma.rank, ma.score, ma.selected,
       ma.estimated_tokens, ma.used, ma.helpful, ma.harmful,
       ma.retrieval_algorithm_version, ma.created_at
FROM memory_access ma JOIN MEMORY m ON m.id = ma.memory_id;

CREATE VIEW v_procedure_effectiveness AS
SELECT p.id AS procedure_id, p.project_id, p.name,
       pv.id AS procedure_version_id, pv.version_no, pv.status AS procedure_version_status,
       pu.outcome, COUNT(pu.id) AS use_count
FROM PROCEDURE p
JOIN PROCEDURE_VERSION pv ON pv.procedure_id = p.id
LEFT JOIN PROCEDURE_USE pu ON pu.procedure_version_id = pv.id
GROUP BY p.id, pv.id, pu.outcome;

CREATE VIEW v_project_active_memories AS
SELECT m.id AS memory_id, m.origin_project_id, m.memory_kind, m.title,
       m.confidence, m.usefulness_count, m.harmful_count, ms.scope_kind,
       ms.project_id AS scope_project_id
FROM MEMORY m JOIN MEMORY_SCOPE ms ON ms.memory_id = m.id
WHERE m.state = 'Active';

CREATE VIEW v_unresolved_review_findings AS
SELECT rf.id AS review_finding_id, rf.review_id, r.delivery_attempt_id,
       r.reviewed_sha, rf.severity, rf.state AS finding_state, rf.criterion_id,
       rf.file_path, rf.line_no, rf.summary, rf.evidence_id
FROM REVIEW_FINDING rf JOIN REVIEW r ON r.id = rf.review_id
WHERE rf.state != 'resolved';

CREATE VIEW v_retention_candidates AS
SELECT a.id AS artifact_id, a.project_id, a.retention_class, a.redaction_state,
       a.byte_size, a.created_at, a.expires_at
FROM ARTIFACT a
WHERE a.expires_at IS NOT NULL
  AND a.expires_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now');

"""
SQL Schema DDL definitions for Diva Memory Engine v3.0.
Contains CREATE TABLE, CREATE INDEX, and FTS5 virtual table statements across all 14 logical domains.
Strict types (STRICT) and foreign key constraints are enforced on all tables.
"""

SCHEMA_PRAGMAS = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 30000;
PRAGMA cache_size = -65536;
PRAGMA temp_store = MEMORY;
PRAGMA mmap_size = 268435456;
PRAGMA wal_autocheckpoint = 1000;
"""

CREATE_TABLES_SQL = """
-- ============================================================================
-- DOMAIN 13: GOVERNANCE & SCHEMA (Must precede tables with FKs)
-- ============================================================================

CREATE TABLE IF NOT EXISTS schema_versions (
    version_id    INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    version_name  TEXT NOT NULL,
    applied_at    TEXT NOT NULL,
    migration_sql TEXT NOT NULL,
    checksum      TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS access_policies (
    policy_id         TEXT NOT NULL PRIMARY KEY,
    target_resource   TEXT NOT NULL,
    resource_type     TEXT NOT NULL,
    domain_partition  TEXT NOT NULL,
    permitted_engines TEXT NOT NULL,
    access_modes      TEXT NOT NULL,
    created_by        TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    expires_at        TEXT,
    active            INTEGER NOT NULL DEFAULT 1
) STRICT;

CREATE INDEX IF NOT EXISTS idx_policies_partition 
ON access_policies (domain_partition, resource_type, active);

CREATE TABLE IF NOT EXISTS audit_events (
    audit_id        TEXT NOT NULL PRIMARY KEY,
    event_type      TEXT NOT NULL,
    target_id       TEXT NOT NULL,
    target_type     TEXT NOT NULL,
    actor_engine    TEXT NOT NULL,
    actor_session   TEXT NOT NULL,
    old_state       TEXT,
    new_state       TEXT,
    event_at        TEXT NOT NULL,
    policy_id       TEXT REFERENCES access_policies(policy_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_events (target_id, target_type, event_at);
CREATE INDEX IF NOT EXISTS idx_audit_actor  ON audit_events (actor_engine, event_at);
CREATE INDEX IF NOT EXISTS idx_audit_type   ON audit_events (event_type, event_at);

-- ============================================================================
-- DOMAIN 14: BACKGROUND JOBS & TRANSACTIONAL OUTBOX
-- ============================================================================

CREATE TABLE IF NOT EXISTS background_jobs (
    job_id          TEXT NOT NULL PRIMARY KEY,
    job_type        TEXT NOT NULL,
    input_data      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'PENDING',
    priority        INTEGER NOT NULL DEFAULT 5,
    max_attempts    INTEGER NOT NULL DEFAULT 3,
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at      TEXT NOT NULL,
    scheduled_at    TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    error_message   TEXT,
    result_data     TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_jobs_status ON background_jobs (status, priority, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_jobs_idem   ON background_jobs (idempotency_key);

CREATE TABLE IF NOT EXISTS background_leases (
    lease_id      TEXT NOT NULL PRIMARY KEY,
    job_id        TEXT NOT NULL REFERENCES background_jobs(job_id) UNIQUE,
    worker_id     TEXT NOT NULL,
    acquired_at   TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    heartbeat_at  TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS outbox_events (
    outbox_id        TEXT NOT NULL PRIMARY KEY,
    event_name       TEXT NOT NULL,
    event_payload    TEXT NOT NULL,
    source_engine    TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    published        INTEGER NOT NULL DEFAULT 0,
    published_at     TEXT,
    publish_attempts INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE INDEX IF NOT EXISTS idx_outbox_unpublished 
ON outbox_events (published, created_at) WHERE published = 0;

-- ============================================================================
-- DOMAIN 01: EXPERIENCE DOMAIN
-- ============================================================================

CREATE TABLE IF NOT EXISTS input_events (
    event_id          TEXT NOT NULL PRIMARY KEY,
    source_engine     TEXT NOT NULL,
    channel           TEXT NOT NULL,
    domain_partition  TEXT NOT NULL CHECK (domain_partition IN ('COGNITIVE','AUTONOMOUS','SHARED')),
    session_id        TEXT NOT NULL,
    raw_content       TEXT NOT NULL,
    content_hash      TEXT NOT NULL,
    received_at       TEXT NOT NULL,
    processed         INTEGER NOT NULL DEFAULT 0,
    processing_job_id TEXT,
    schema_version    INTEGER NOT NULL DEFAULT 1
) STRICT;

CREATE INDEX IF NOT EXISTS idx_input_events_session ON input_events (session_id, received_at);
CREATE INDEX IF NOT EXISTS idx_input_events_source  ON input_events (source_engine, received_at);
CREATE INDEX IF NOT EXISTS idx_input_events_pending ON input_events (processed) WHERE processed = 0;
CREATE INDEX IF NOT EXISTS idx_input_events_hash    ON input_events (content_hash);

CREATE TABLE IF NOT EXISTS experiences (
    experience_id         TEXT NOT NULL PRIMARY KEY,
    source_event_id       TEXT REFERENCES input_events(event_id) ON DELETE RESTRICT,
    session_id            TEXT NOT NULL,
    domain_partition      TEXT NOT NULL CHECK (domain_partition IN ('COGNITIVE','AUTONOMOUS','SHARED')),
    experience_summary    TEXT NOT NULL,
    participants          TEXT NOT NULL,
    world_time_start      TEXT,
    world_time_end        TEXT,
    diva_time_recorded    TEXT NOT NULL,
    development_status    TEXT NOT NULL DEFAULT 'RAW',
    validity_status       TEXT NOT NULL DEFAULT 'CURRENT',
    retention_status      TEXT NOT NULL DEFAULT 'ACTIVE',
    permanent_importance  REAL NOT NULL DEFAULT 0.5 CHECK (permanent_importance BETWEEN 0.0 AND 1.0),
    temporary_importance  REAL NOT NULL DEFAULT 0.0 CHECK (temporary_importance BETWEEN 0.0 AND 1.0),
    access_count          INTEGER NOT NULL DEFAULT 0,
    last_accessed_at      TEXT,
    provenance_hash       TEXT NOT NULL,
    schema_version        INTEGER NOT NULL DEFAULT 1
) STRICT;

CREATE INDEX IF NOT EXISTS idx_experiences_session     ON experiences (session_id, diva_time_recorded);
CREATE INDEX IF NOT EXISTS idx_experiences_world_time  ON experiences (world_time_start, world_time_end);
CREATE INDEX IF NOT EXISTS idx_experiences_status      ON experiences (development_status, validity_status);
CREATE INDEX IF NOT EXISTS idx_experiences_importance  ON experiences (permanent_importance DESC);
CREATE INDEX IF NOT EXISTS idx_experiences_partition   ON experiences (domain_partition);
CREATE INDEX IF NOT EXISTS idx_experiences_hash        ON experiences (provenance_hash);

CREATE TABLE IF NOT EXISTS experience_payloads (
    payload_id      TEXT NOT NULL PRIMARY KEY,
    experience_id   TEXT NOT NULL REFERENCES experiences(experience_id) ON DELETE RESTRICT,
    payload_format  TEXT NOT NULL,
    payload_data    BLOB NOT NULL,
    content_hash    TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    is_archived     INTEGER NOT NULL DEFAULT 0,
    archive_path    TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_payloads_experience ON experience_payloads (experience_id);

-- ============================================================================
-- DOMAIN 04: ENTITY DOMAIN
-- ============================================================================

CREATE TABLE IF NOT EXISTS entities (
    entity_id           TEXT NOT NULL PRIMARY KEY,
    canonical_name      TEXT NOT NULL,
    entity_type         TEXT NOT NULL,
    domain_partition    TEXT NOT NULL,
    first_observed_at   TEXT NOT NULL,
    last_observed_at    TEXT NOT NULL,
    observation_count   INTEGER NOT NULL DEFAULT 1,
    status              TEXT NOT NULL DEFAULT 'ACTIVE',
    merged_into         TEXT REFERENCES entities(entity_id),
    provenance_hash     TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_entities_name      ON entities (canonical_name, entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_partition ON entities (domain_partition, status);

CREATE TABLE IF NOT EXISTS entity_aliases (
    alias_id         TEXT NOT NULL PRIMARY KEY,
    entity_id        TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE RESTRICT,
    alias_text       TEXT NOT NULL,
    alias_type       TEXT NOT NULL,
    confidence       REAL NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0.0 AND 1.0),
    source_engine    TEXT NOT NULL,
    established_at   TEXT NOT NULL,
    superseded       INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_alias_text ON entity_aliases (alias_text, alias_type) WHERE superseded = 0;
CREATE INDEX IF NOT EXISTS idx_aliases_entity   ON entity_aliases (entity_id, superseded);

-- ============================================================================
-- DOMAIN 02: KNOWLEDGE (CLAIMS) DOMAIN
-- ============================================================================

CREATE TABLE IF NOT EXISTS claims (
    claim_id              TEXT NOT NULL PRIMARY KEY,
    subject_entity_id     TEXT REFERENCES entities(entity_id) ON DELETE RESTRICT,
    predicate             TEXT NOT NULL,
    object_value          TEXT NOT NULL,
    canonical_statement   TEXT NOT NULL,
    epistemic_type        TEXT NOT NULL CHECK (epistemic_type IN
                            ('OBSERVATION','REPORTED','INFERENCE','INTERPRETATION','OPINION','UNKNOWN')),
    evidence_status       TEXT NOT NULL DEFAULT 'UNVERIFIED',
    lifecycle             TEXT NOT NULL DEFAULT 'ACTIVE',
    domain_partition      TEXT NOT NULL,
    source_engine         TEXT NOT NULL,
    source_session_id     TEXT NOT NULL,
    source_experience_id  TEXT REFERENCES experiences(experience_id) ON DELETE RESTRICT,
    world_time_start      TEXT,
    world_time_end        TEXT,
    diva_time_recorded    TEXT NOT NULL,
    provenance_hash       TEXT NOT NULL UNIQUE,
    version               INTEGER NOT NULL DEFAULT 1,
    schema_version        INTEGER NOT NULL DEFAULT 1
) STRICT;

CREATE INDEX IF NOT EXISTS idx_claims_entity     ON claims (subject_entity_id, predicate);
CREATE INDEX IF NOT EXISTS idx_claims_epistemic  ON claims (epistemic_type, evidence_status);
CREATE INDEX IF NOT EXISTS idx_claims_lifecycle  ON claims (lifecycle, domain_partition);
CREATE INDEX IF NOT EXISTS idx_claims_world_time ON claims (world_time_start, world_time_end);
CREATE INDEX IF NOT EXISTS idx_claims_source     ON claims (source_engine, source_session_id);

CREATE TABLE IF NOT EXISTS entity_attributes (
    attribute_id      TEXT NOT NULL PRIMARY KEY,
    entity_id         TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE RESTRICT,
    attribute_key     TEXT NOT NULL,
    attribute_value   TEXT NOT NULL,
    epistemic_type    TEXT NOT NULL,
    valid_from        TEXT,
    valid_until       TEXT,
    source_claim_id   TEXT REFERENCES claims(claim_id) ON DELETE RESTRICT,
    created_at        TEXT NOT NULL,
    superseded        INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE INDEX IF NOT EXISTS idx_attributes_entity ON entity_attributes (entity_id, attribute_key, superseded);

CREATE TABLE IF NOT EXISTS claim_assessments (
    assessment_id      TEXT NOT NULL PRIMARY KEY,
    claim_id           TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE RESTRICT,
    assessor_engine    TEXT NOT NULL,
    assessor_session   TEXT NOT NULL,
    confidence         REAL NOT NULL CHECK (confidence BETWEEN 0.0 AND 1.0),
    rationale          TEXT NOT NULL,
    assessment_method  TEXT NOT NULL,
    assessed_at        TEXT NOT NULL,
    superseded         INTEGER NOT NULL DEFAULT 0,
    superseded_by      TEXT REFERENCES claim_assessments(assessment_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_assessments_claim      ON claim_assessments (claim_id, superseded);
CREATE INDEX IF NOT EXISTS idx_assessments_assessor   ON claim_assessments (assessor_engine, claim_id);

CREATE TABLE IF NOT EXISTS claim_versions (
    version_id         TEXT NOT NULL PRIMARY KEY,
    claim_id           TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE RESTRICT,
    version_number     INTEGER NOT NULL,
    previous_version   TEXT REFERENCES claim_versions(version_id),
    change_type        TEXT NOT NULL,
    old_state          TEXT NOT NULL,
    new_state          TEXT NOT NULL,
    changed_by         TEXT NOT NULL,
    change_reason      TEXT NOT NULL,
    changed_at         TEXT NOT NULL
) STRICT;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_claim_versions ON claim_versions (claim_id, version_number);
CREATE INDEX IF NOT EXISTS idx_claim_versions_history ON claim_versions (claim_id, changed_at);

-- ============================================================================
-- DOMAIN 03: PROVENANCE DOMAIN
-- ============================================================================

CREATE TABLE IF NOT EXISTS evidence_references (
    evidence_id          TEXT NOT NULL PRIMARY KEY,
    claim_id             TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE RESTRICT,
    source_memory_id     TEXT REFERENCES experiences(experience_id) ON DELETE RESTRICT,
    source_claim_id      TEXT REFERENCES claims(claim_id) ON DELETE RESTRICT,
    relationship         TEXT NOT NULL CHECK (relationship IN ('SUPPORTS','OPPOSES','CONTEXTUALIZES')),
    weight               REAL NOT NULL DEFAULT 0.5 CHECK (weight BETWEEN 0.0 AND 1.0),
    added_by             TEXT NOT NULL,
    added_at             TEXT NOT NULL,
    CHECK (source_memory_id IS NOT NULL OR source_claim_id IS NOT NULL)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_evidence_claim    ON evidence_references (claim_id, relationship);
CREATE INDEX IF NOT EXISTS idx_evidence_memory   ON evidence_references (source_memory_id);

CREATE TABLE IF NOT EXISTS derivation_links (
    link_id              TEXT NOT NULL PRIMARY KEY,
    derived_id           TEXT NOT NULL,
    derived_type         TEXT NOT NULL,
    source_id            TEXT NOT NULL,
    source_type          TEXT NOT NULL,
    derivation_method    TEXT NOT NULL,
    derived_at           TEXT NOT NULL,
    deriving_engine      TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_derivation_derived ON derivation_links (derived_id, derived_type);
CREATE INDEX IF NOT EXISTS idx_derivation_source  ON derivation_links (source_id, source_type);

-- ============================================================================
-- DOMAIN 05: ASSOCIATION DOMAIN
-- ============================================================================

CREATE TABLE IF NOT EXISTS memory_relationships (
    relationship_id    TEXT NOT NULL PRIMARY KEY,
    source_memory_id   TEXT NOT NULL,
    target_memory_id   TEXT NOT NULL,
    relationship_type  TEXT NOT NULL,
    confidence         REAL NOT NULL DEFAULT 0.5 CHECK (confidence BETWEEN 0.0 AND 1.0),
    established_by     TEXT NOT NULL,
    established_at     TEXT NOT NULL,
    superseded         INTEGER NOT NULL DEFAULT 0,
    development_job_id TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_mem_rel_source ON memory_relationships (source_memory_id, relationship_type);
CREATE INDEX IF NOT EXISTS idx_mem_rel_target ON memory_relationships (target_memory_id, relationship_type);
CREATE INDEX IF NOT EXISTS idx_mem_rel_type   ON memory_relationships (relationship_type, superseded);

CREATE TABLE IF NOT EXISTS claim_relationships (
    relationship_id      TEXT NOT NULL PRIMARY KEY,
    claim_id_source      TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE RESTRICT,
    claim_id_target      TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE RESTRICT,
    relationship_type    TEXT NOT NULL,
    confidence           REAL NOT NULL DEFAULT 0.5,
    established_by       TEXT NOT NULL,
    established_at       TEXT NOT NULL,
    supporting_evidence  TEXT NOT NULL DEFAULT '[]',
    superseded           INTEGER NOT NULL DEFAULT 0,
    CHECK (claim_id_source != claim_id_target)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_cl_rel_source ON claim_relationships (claim_id_source, relationship_type);
CREATE INDEX IF NOT EXISTS idx_cl_rel_target ON claim_relationships (claim_id_target, relationship_type);

-- ============================================================================
-- DOMAIN 06: REPRESENTATION DOMAIN
-- ============================================================================

CREATE TABLE IF NOT EXISTS memory_representations (
    representation_id         TEXT NOT NULL PRIMARY KEY,
    source_experience_id      TEXT REFERENCES experiences(experience_id) ON DELETE RESTRICT,
    parent_representation_id  TEXT REFERENCES memory_representations(representation_id),
    representation_type       TEXT NOT NULL,
    development_status        TEXT NOT NULL DEFAULT 'RAW',
    validity_status           TEXT NOT NULL DEFAULT 'CURRENT',
    domain_partition          TEXT NOT NULL,
    content                   TEXT NOT NULL,
    content_hash              TEXT NOT NULL,
    producing_engine          TEXT NOT NULL,
    producing_method          TEXT NOT NULL,
    version                   INTEGER NOT NULL DEFAULT 1,
    created_at                TEXT NOT NULL,
    superseded_at             TEXT,
    claims_derived            TEXT NOT NULL DEFAULT '[]'
) STRICT;

CREATE INDEX IF NOT EXISTS idx_repr_experience ON memory_representations (source_experience_id);
CREATE INDEX IF NOT EXISTS idx_repr_parent     ON memory_representations (parent_representation_id);
CREATE INDEX IF NOT EXISTS idx_repr_type       ON memory_representations (representation_type, development_status);
CREATE INDEX IF NOT EXISTS idx_repr_partition  ON memory_representations (domain_partition, validity_status);

CREATE TABLE IF NOT EXISTS representation_lineage (
    lineage_id          TEXT NOT NULL PRIMARY KEY,
    representation_id   TEXT NOT NULL REFERENCES memory_representations(representation_id),
    parent_id           TEXT REFERENCES memory_representations(representation_id),
    lineage_depth       INTEGER NOT NULL DEFAULT 0,
    derivation_type     TEXT NOT NULL,
    created_at          TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_lineage_repr   ON representation_lineage (representation_id);
CREATE INDEX IF NOT EXISTS idx_lineage_depth  ON representation_lineage (lineage_depth, representation_id);

-- ============================================================================
-- DOMAIN 07: APPRAISAL DOMAIN
-- ============================================================================

CREATE TABLE IF NOT EXISTS memory_appraisals (
    appraisal_id      TEXT NOT NULL PRIMARY KEY,
    experience_id     TEXT NOT NULL REFERENCES experiences(experience_id) ON DELETE RESTRICT,
    appraising_engine TEXT NOT NULL,
    appraisal_type    TEXT NOT NULL,
    appraisal_content TEXT NOT NULL,
    confidence        REAL NOT NULL CHECK (confidence BETWEEN 0.0 AND 1.0),
    appraised_at      TEXT NOT NULL,
    session_id        TEXT NOT NULL,
    version           INTEGER NOT NULL DEFAULT 1,
    superseded        INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE INDEX IF NOT EXISTS idx_appraisal_experience ON memory_appraisals (experience_id, appraising_engine);
CREATE INDEX IF NOT EXISTS idx_appraisal_type       ON memory_appraisals (appraisal_type, superseded);

CREATE TABLE IF NOT EXISTS appraisal_history (
    history_id       TEXT NOT NULL PRIMARY KEY,
    appraisal_id     TEXT NOT NULL REFERENCES memory_appraisals(appraisal_id),
    version_number   INTEGER NOT NULL,
    content_snapshot TEXT NOT NULL,
    recorded_at      TEXT NOT NULL,
    reason           TEXT NOT NULL
) STRICT;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_appraisal_history ON appraisal_history (appraisal_id, version_number);

-- ============================================================================
-- DOMAIN 08: DEVELOPMENT DOMAIN
-- ============================================================================

CREATE TABLE IF NOT EXISTS development_requests (
    request_id             TEXT NOT NULL PRIMARY KEY,
    operation_type         TEXT NOT NULL,
    initiating_subsystem   TEXT NOT NULL,
    requesting_engine      TEXT,
    target_memory_ids      TEXT NOT NULL DEFAULT '[]',
    target_claim_ids       TEXT NOT NULL DEFAULT '[]',
    development_objective  TEXT NOT NULL,
    evidence_requirements  TEXT NOT NULL DEFAULT '[]',
    parent_operation_id    TEXT REFERENCES development_requests(request_id),
    processing_depth       INTEGER NOT NULL DEFAULT 0,
    max_processing_depth   INTEGER NOT NULL DEFAULT 5,
    resource_budget        TEXT NOT NULL,
    idempotency_key        TEXT NOT NULL UNIQUE,
    priority               INTEGER NOT NULL DEFAULT 5,
    status                 TEXT NOT NULL DEFAULT 'PENDING',
    requested_at           TEXT NOT NULL,
    deadline_at            TEXT,
    started_at             TEXT,
    completed_at           TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_dev_req_status ON development_requests (status, priority, requested_at);
CREATE INDEX IF NOT EXISTS idx_dev_req_parent ON development_requests (parent_operation_id);
CREATE INDEX IF NOT EXISTS idx_dev_req_idem   ON development_requests (idempotency_key);

CREATE TABLE IF NOT EXISTS development_proposals (
    proposal_id          TEXT NOT NULL PRIMARY KEY,
    request_id           TEXT NOT NULL REFERENCES development_requests(request_id),
    originating_engine   TEXT NOT NULL,
    result_status        TEXT NOT NULL,
    proposed_claims      TEXT NOT NULL DEFAULT '[]',
    proposed_relations   TEXT NOT NULL DEFAULT '[]',
    supporting_evidence  TEXT NOT NULL DEFAULT '[]',
    opposing_evidence    TEXT NOT NULL DEFAULT '[]',
    unresolved_questions TEXT NOT NULL DEFAULT '[]',
    rationale            TEXT NOT NULL,
    produced_at          TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_proposals_request ON development_proposals (request_id, result_status);

CREATE TABLE IF NOT EXISTS development_reviews (
    review_id         TEXT NOT NULL PRIMARY KEY,
    proposal_id       TEXT NOT NULL REFERENCES development_proposals(proposal_id),
    reviewing_engine  TEXT NOT NULL,
    decision          TEXT NOT NULL,
    decision_reason   TEXT NOT NULL,
    reviewed_at       TEXT NOT NULL,
    resulting_records TEXT NOT NULL DEFAULT '[]'
) STRICT;

CREATE INDEX IF NOT EXISTS idx_reviews_proposal ON development_reviews (proposal_id, decision);

-- ============================================================================
-- DOMAIN 09: CONSOLIDATION DOMAIN
-- ============================================================================

CREATE TABLE IF NOT EXISTS consolidation_jobs (
    job_id               TEXT NOT NULL PRIMARY KEY,
    trigger_type         TEXT NOT NULL,
    source_memory_ids    TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'PENDING',
    seven_gate_results   TEXT,
    all_gates_passed     INTEGER,
    resulting_repr_id    TEXT REFERENCES memory_representations(representation_id),
    initiated_at         TEXT NOT NULL,
    completed_at         TEXT,
    failure_reason       TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_consol_jobs_status ON consolidation_jobs (status, initiated_at);

CREATE TABLE IF NOT EXISTS consolidation_coverage (
    coverage_id       TEXT NOT NULL PRIMARY KEY,
    job_id            TEXT NOT NULL REFERENCES consolidation_jobs(job_id),
    source_memory_id  TEXT NOT NULL REFERENCES experiences(experience_id),
    claim_ids         TEXT NOT NULL DEFAULT '[]',
    covered_claim_ids TEXT NOT NULL DEFAULT '[]',
    coverage_pct      REAL,
    CHECK (coverage_pct IS NULL OR coverage_pct BETWEEN 0.0 AND 1.0)
) STRICT;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_coverage ON consolidation_coverage (job_id, source_memory_id);

CREATE TABLE IF NOT EXISTS residual_claims (
    residual_id      TEXT NOT NULL PRIMARY KEY,
    job_id           TEXT NOT NULL REFERENCES consolidation_jobs(job_id),
    claim_id         TEXT NOT NULL REFERENCES claims(claim_id),
    reason           TEXT NOT NULL,
    created_at       TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_residual_job ON residual_claims (job_id);

-- ============================================================================
-- DOMAIN 10: RETRIEVAL DOMAIN
-- ============================================================================

CREATE TABLE IF NOT EXISTS retrieval_events (
    retrieval_id      TEXT NOT NULL PRIMARY KEY,
    requesting_engine TEXT NOT NULL,
    retrieval_intent  TEXT NOT NULL,
    query_text        TEXT,
    retrieved_ids     TEXT NOT NULL DEFAULT '[]',
    retrieved_count   INTEGER NOT NULL DEFAULT 0,
    retrieval_methods TEXT NOT NULL DEFAULT '[]',
    total_latency_ms  INTEGER,
    session_id        TEXT NOT NULL,
    retrieved_at      TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_retrieval_session ON retrieval_events (session_id, retrieved_at);
CREATE INDEX IF NOT EXISTS idx_retrieval_engine  ON retrieval_events (requesting_engine, retrieval_intent);

CREATE TABLE IF NOT EXISTS memory_embeddings_fallback (
    embedding_id  TEXT NOT NULL PRIMARY KEY,
    memory_id     TEXT NOT NULL,
    model_id      TEXT NOT NULL,
    embedding     BLOB NOT NULL,
    dimensions    INTEGER NOT NULL,
    created_at    TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_embed_memory ON memory_embeddings_fallback (memory_id);

-- ============================================================================
-- DOMAIN 11: RETENTION DOMAIN
-- ============================================================================

CREATE TABLE IF NOT EXISTS retention_records (
    record_id              TEXT NOT NULL PRIMARY KEY,
    memory_id              TEXT NOT NULL,
    memory_type            TEXT NOT NULL,
    permanent_importance   REAL NOT NULL DEFAULT 0.5,
    development_priority   REAL NOT NULL DEFAULT 0.5,
    retention_status       TEXT NOT NULL DEFAULT 'ACTIVE',
    dependency_count       INTEGER NOT NULL DEFAULT 0,
    consolidation_eligible INTEGER NOT NULL DEFAULT 0,
    archival_eligible      INTEGER NOT NULL DEFAULT 0,
    last_evaluated_at      TEXT,
    evaluation_trigger     TEXT
) STRICT;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_retention ON retention_records (memory_id, memory_type);
CREATE INDEX IF NOT EXISTS idx_retention_status  ON retention_records (retention_status, archival_eligible);

CREATE TABLE IF NOT EXISTS archive_records (
    archive_id        TEXT NOT NULL PRIMARY KEY,
    memory_id         TEXT NOT NULL,
    memory_type       TEXT NOT NULL,
    archive_path      TEXT NOT NULL,
    archived_at       TEXT NOT NULL,
    compression_type  TEXT NOT NULL DEFAULT 'ZSTD',
    original_size_kb  INTEGER,
    archived_size_kb  INTEGER,
    checksum          TEXT NOT NULL,
    retrieval_tested  INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE TABLE IF NOT EXISTS memory_dependencies (
    dependency_id    TEXT NOT NULL PRIMARY KEY,
    dependent_id     TEXT NOT NULL,
    dependency_type  TEXT NOT NULL,
    source_id        TEXT NOT NULL,
    created_at       TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_dependencies_source    ON memory_dependencies (source_id);
CREATE INDEX IF NOT EXISTS idx_dependencies_dependent ON memory_dependencies (dependent_id);

-- ============================================================================
-- DOMAIN 12: CONTINUITY DOMAIN
-- ============================================================================

CREATE TABLE IF NOT EXISTS continuity_checkpoints (
    checkpoint_id              TEXT NOT NULL PRIMARY KEY,
    session_id                 TEXT NOT NULL,
    schema_version             INTEGER NOT NULL,
    workspace_snapshot_ref     TEXT,
    attention_snapshot_ref     TEXT,
    activity_snapshot_refs     TEXT NOT NULL DEFAULT '[]',
    active_goal_refs           TEXT NOT NULL DEFAULT '[]',
    unresolved_commitment_refs TEXT NOT NULL DEFAULT '[]',
    created_at                 TEXT NOT NULL,
    valid                      INTEGER NOT NULL DEFAULT 1,
    restoration_attempted      INTEGER NOT NULL DEFAULT 0,
    restoration_succeeded      INTEGER,
    domain_partition           TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_checkpoint_session ON continuity_checkpoints (session_id, domain_partition, created_at);
CREATE INDEX IF NOT EXISTS idx_checkpoint_valid   ON continuity_checkpoints (valid, domain_partition);

-- ============================================================================
-- FTS5 VIRTUAL TABLE (DERIVED PROJECTION INDEX)
-- ============================================================================

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    memory_id UNINDEXED,
    experience_summary,
    canonical_statements,
    entity_names,
    tokenize = 'porter unicode61'
);
"""

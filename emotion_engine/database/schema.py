"""
Relational Database Schema for Diva Emotion Engine v1.0.0.
Contains all 16 SQLite tables, check constraints, foreign keys (ON DELETE RESTRICT),
and secondary indexes specified in Part 4 Section B.
"""

SCHEMA_SQL = """
-- ==============================================================================
-- 1. Active and Historical Emotion Instances
-- ==============================================================================
CREATE TABLE IF NOT EXISTS emotion_records (
    emotion_id TEXT PRIMARY KEY,
    category_name TEXT NOT NULL,
    emotion_type TEXT NOT NULL CHECK (emotion_type IN ('PRIMITIVE', 'COMPLEX')),
    current_intensity REAL NOT NULL CHECK (current_intensity >= 0.0 AND current_intensity <= 1.0),
    state TEXT NOT NULL CHECK (state IN ('TRIGGERED', 'ACTIVE_SURGE', 'SUSTAINED_DECAY', 'REGULATING', 'EXTINCTION')),
    created_at TEXT NOT NULL,
    last_renewed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_emotion_records_state ON emotion_records (state);
CREATE INDEX IF NOT EXISTS idx_emotion_records_category ON emotion_records (category_name);

-- ==============================================================================
-- 2. Emotion Mathematical Intensities
-- ==============================================================================
CREATE TABLE IF NOT EXISTS emotion_intensities (
    intensity_id TEXT PRIMARY KEY,
    emotion_id TEXT NOT NULL UNIQUE,
    raw_intensity REAL NOT NULL,
    calibrated_intensity REAL NOT NULL,
    trigger_contribution REAL NOT NULL,
    mood_contribution REAL NOT NULL,
    personality_multiplier REAL NOT NULL,
    calculated_at TEXT NOT NULL,
    FOREIGN KEY (emotion_id) REFERENCES emotion_records(emotion_id) ON DELETE RESTRICT
);

-- ==============================================================================
-- 3. Causal Emotional Triggers
-- ==============================================================================
CREATE TABLE IF NOT EXISTS emotion_triggers (
    trigger_id TEXT PRIMARY KEY,
    emotion_id TEXT NOT NULL,
    source_engine TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    assessed_significance REAL NOT NULL,
    perceived_valence REAL NOT NULL,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (emotion_id) REFERENCES emotion_records(emotion_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_emotion_triggers_source ON emotion_triggers (source_engine, trigger_type);
CREATE INDEX IF NOT EXISTS idx_emotion_triggers_emotion ON emotion_triggers (emotion_id);

-- ==============================================================================
-- 4. Contextual Surrounding Metadata
-- ==============================================================================
CREATE TABLE IF NOT EXISTS emotion_contexts (
    context_id TEXT PRIMARY KEY,
    emotion_id TEXT NOT NULL UNIQUE,
    social_interlocutor_id TEXT,
    environmental_setting TEXT NOT NULL,
    active_task_id TEXT,
    uncertainty_score REAL NOT NULL,
    context_metadata_json TEXT NOT NULL,
    FOREIGN KEY (emotion_id) REFERENCES emotion_records(emotion_id) ON DELETE RESTRICT
);

-- ==============================================================================
-- 5. Emotional Transitions
-- ==============================================================================
CREATE TABLE IF NOT EXISTS emotion_transitions (
    transition_id TEXT PRIMARY KEY,
    emotion_id TEXT NOT NULL,
    previous_state TEXT NOT NULL,
    new_state TEXT NOT NULL,
    triggering_factor TEXT NOT NULL,
    intensity_delta REAL NOT NULL,
    transitioned_at TEXT NOT NULL,
    FOREIGN KEY (emotion_id) REFERENCES emotion_records(emotion_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_emotion_transitions_emotion ON emotion_transitions (emotion_id, transitioned_at);

-- ==============================================================================
-- 6. Mixed Emotion Blends
-- ==============================================================================
CREATE TABLE IF NOT EXISTS emotion_mixed_states (
    mixed_state_id TEXT PRIMARY KEY,
    coexisting_emotion_ids_json TEXT NOT NULL,
    primary_blend_name TEXT,
    coherence_score REAL NOT NULL,
    observed_at TEXT NOT NULL
);

-- ==============================================================================
-- 7. Emotional Conflicts
-- ==============================================================================
CREATE TABLE IF NOT EXISTS emotion_conflicts (
    conflict_id TEXT PRIMARY KEY,
    emotion_a_id TEXT NOT NULL,
    emotion_b_id TEXT NOT NULL,
    conflict_category TEXT NOT NULL,
    tension_metric REAL NOT NULL,
    is_active INTEGER NOT NULL CHECK (is_active IN (0, 1)),
    detected_at TEXT NOT NULL,
    FOREIGN KEY (emotion_a_id) REFERENCES emotion_records(emotion_id) ON DELETE RESTRICT,
    FOREIGN KEY (emotion_b_id) REFERENCES emotion_records(emotion_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_emotion_conflicts_active ON emotion_conflicts (is_active);

-- ==============================================================================
-- 8. Persistent Circumplex Mood
-- ==============================================================================
CREATE TABLE IF NOT EXISTS emotion_mood_record (
    mood_id TEXT PRIMARY KEY,
    valence REAL NOT NULL CHECK (valence >= -1.0 AND valence <= 1.0),
    arousal REAL NOT NULL CHECK (arousal >= -1.0 AND arousal <= 1.0),
    dominance REAL NOT NULL CHECK (dominance >= -1.0 AND dominance <= 1.0),
    label_descriptor TEXT NOT NULL,
    stability_metric REAL NOT NULL,
    updated_at TEXT NOT NULL
);

-- ==============================================================================
-- 9. Mood Historical Trajectory
-- ==============================================================================
CREATE TABLE IF NOT EXISTS emotion_mood_history (
    history_id TEXT PRIMARY KEY,
    valence_snapshot REAL NOT NULL,
    arousal_snapshot REAL NOT NULL,
    dominance_snapshot REAL NOT NULL,
    driving_emotion_ids_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_emotion_mood_history_time ON emotion_mood_history (recorded_at);

-- ==============================================================================
-- 10. Predefined Decay Profiles
-- ==============================================================================
CREATE TABLE IF NOT EXISTS emotion_decay_profiles (
    profile_id TEXT PRIMARY KEY,
    emotion_category TEXT NOT NULL UNIQUE,
    half_life_seconds REAL NOT NULL,
    decay_curve_type TEXT NOT NULL,
    quiescent_baseline REAL NOT NULL
);

-- ==============================================================================
-- 11. Emotional Regulation Log
-- ==============================================================================
CREATE TABLE IF NOT EXISTS emotion_regulation_records (
    regulation_id TEXT PRIMARY KEY,
    emotion_id TEXT NOT NULL,
    strategy_used TEXT NOT NULL,
    intensity_before REAL NOT NULL,
    intensity_after REAL NOT NULL,
    was_successful INTEGER NOT NULL CHECK (was_successful IN (0, 1)),
    executed_at TEXT NOT NULL,
    FOREIGN KEY (emotion_id) REFERENCES emotion_records(emotion_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_emotion_regulation_emotion ON emotion_regulation_records (emotion_id);

-- ==============================================================================
-- 12. Emotional Tendencies & Sensitivities
-- ==============================================================================
CREATE TABLE IF NOT EXISTS emotion_tendencies (
    tendency_id TEXT PRIMARY KEY,
    dimension_name TEXT NOT NULL UNIQUE,
    current_value REAL NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    is_constitutional_baseline INTEGER NOT NULL CHECK (is_constitutional_baseline IN (0, 1)),
    updated_at TEXT NOT NULL
);

-- ==============================================================================
-- 13. Emotional Learning History
-- ==============================================================================
CREATE TABLE IF NOT EXISTS emotion_learning_records (
    learning_record_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    dimension_name TEXT NOT NULL,
    old_value REAL NOT NULL,
    new_value REAL NOT NULL,
    applied_at TEXT NOT NULL
);

-- ==============================================================================
-- 14. Permanent Affective History
-- ==============================================================================
CREATE TABLE IF NOT EXISTS emotion_historical_events (
    history_entry_id TEXT PRIMARY KEY,
    emotion_id TEXT NOT NULL,
    category TEXT NOT NULL,
    peak_intensity REAL NOT NULL,
    duration_seconds INTEGER NOT NULL,
    resolution_type TEXT NOT NULL,
    closed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_emotion_historical_events_closed ON emotion_historical_events (closed_at);
CREATE INDEX IF NOT EXISTS idx_emotion_historical_events_cat ON emotion_historical_events (category);

-- ==============================================================================
-- 15. Causal Provenance
-- ==============================================================================
CREATE TABLE IF NOT EXISTS emotion_provenance (
    provenance_id TEXT PRIMARY KEY,
    emotion_id TEXT NOT NULL UNIQUE,
    source_engine TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    derivation_chain_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (emotion_id) REFERENCES emotion_records(emotion_id) ON DELETE RESTRICT
);

-- ==============================================================================
-- 16. Append-Only State Transition Audit Events
-- ==============================================================================
CREATE TABLE IF NOT EXISTS emotion_lifecycle_events (
    event_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('EMOTION', 'MOOD', 'REGULATION', 'TENDENCY')),
    entity_id TEXT NOT NULL,
    previous_state TEXT,
    new_state TEXT NOT NULL,
    transition_reason TEXT NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_emotion_lifecycle_events_time ON emotion_lifecycle_events (timestamp);
CREATE INDEX IF NOT EXISTS idx_emotion_lifecycle_events_entity ON emotion_lifecycle_events (entity_id);
"""

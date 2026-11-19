"""
Unit and integration tests for Part 2: Relational Persistence Store & Lifecycle Manager.
Verifies all 16 SQLite tables, foreign key restrictions, atomic rollbacks,
FSM state transitions, active pool bounding (max 10), and crash recovery.
"""

import sqlite3
import uuid
import pytest

from emotion_engine.database.connection import DatabaseConnectionFactory
from emotion_engine.database.migrations import MigrationRunner
from emotion_engine.lifecycle.manager import (
    EmotionalLifecycleManager,
    InvalidEmotionStateTransitionError,
    MAX_ACTIVE_EMOTION_POOL_SIZE,
)
from emotion_engine.types.enums import (
    EmotionState,
    EmotionType,
    TriggerSource,
)


@pytest.fixture
def db_factory():
    """Provides an initialized in-memory database connection factory."""
    factory = DatabaseConnectionFactory(":memory:")
    runner = MigrationRunner(factory)
    runner.apply_migrations()
    yield factory
    factory.close()


@pytest.fixture
def lifecycle_mgr(db_factory):
    """Provides an EmotionalLifecycleManager backed by the initialized database."""
    return EmotionalLifecycleManager(db_factory)


def test_schema_and_migrations_initialization(db_factory):
    """Verify all 16 tables exist, decay profiles seeded, tendencies seeded, and initial mood created."""
    with db_factory.read_cursor() as cursor:
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        )
        tables = {row["name"] for row in cursor.fetchall()}

        expected_16_tables = {
            "emotion_records",
            "emotion_intensities",
            "emotion_triggers",
            "emotion_contexts",
            "emotion_transitions",
            "emotion_mixed_states",
            "emotion_conflicts",
            "emotion_mood_record",
            "emotion_mood_history",
            "emotion_decay_profiles",
            "emotion_regulation_records",
            "emotion_tendencies",
            "emotion_learning_records",
            "emotion_historical_events",
            "emotion_provenance",
            "emotion_lifecycle_events",
        }
        for tbl in expected_16_tables:
            assert tbl in tables, f"Table {tbl} must exist in database schema"

        # Verify decay profiles seeded (30 emotions)
        cursor.execute("SELECT count(*) as cnt FROM emotion_decay_profiles;")
        assert cursor.fetchone()["cnt"] == 30

        # Verify constitutional tendencies seeded
        cursor.execute("SELECT count(*) as cnt FROM emotion_tendencies WHERE is_constitutional_baseline = 1;")
        assert cursor.fetchone()["cnt"] >= 6

        # Verify default neutral mood seeded
        cursor.execute("SELECT * FROM emotion_mood_record;")
        mood_row = cursor.fetchone()
        assert mood_row is not None
        assert mood_row["label_descriptor"] == "Equanimous Neutral"
        assert mood_row["valence"] == 0.0


def test_foreign_key_on_delete_restrict(db_factory, lifecycle_mgr):
    """Verify ON DELETE RESTRICT prevents cascading deletions of emotion records."""
    rec = lifecycle_mgr.create_emotion(
        category_name="Happiness",
        emotion_type=EmotionType.PRIMITIVE,
        initial_intensity=0.8,
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="EVT-01",
        trigger_type="TEST_TRIGGER",
        assessed_significance=0.8,
        perceived_valence=0.9,
        trigger_contribution=0.5,
        mood_contribution=0.1,
        personality_multiplier=1.0,
    )

    # Attempting to delete emotion_record directly must fail due to foreign key children
    with pytest.raises(sqlite3.IntegrityError):
        with db_factory.write_transaction() as cursor:
            cursor.execute("DELETE FROM emotion_records WHERE emotion_id = ?;", (str(rec.emotion_id),))


def test_atomic_transaction_rollback(db_factory):
    """Verify complete rollback on exception inside write_transaction."""
    with db_factory.read_cursor() as cursor:
        cursor.execute("SELECT count(*) as cnt FROM emotion_tendencies;")
        initial_count = cursor.fetchone()["cnt"]

    # Execute a failing transaction
    with pytest.raises(RuntimeError):
        with db_factory.write_transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO emotion_tendencies (
                    tendency_id, dimension_name, current_value, version,
                    is_constitutional_baseline, updated_at
                ) VALUES (?, 'test.failing.tendency', 1.0, 1, 0, '2026-11-19T00:00:00Z');
                """,
                (str(uuid.uuid4()),),
            )
            raise RuntimeError("Simulated transaction failure!")

    # Verify no row was committed
    with db_factory.read_cursor() as cursor:
        cursor.execute("SELECT count(*) as cnt FROM emotion_tendencies;")
        assert cursor.fetchone()["cnt"] == initial_count


def test_fsm_valid_and_invalid_state_transitions(lifecycle_mgr):
    """Verify closed deterministic FSM transitions for an emotion instance."""
    rec = lifecycle_mgr.create_emotion(
        category_name="Curiosity",
        emotion_type=EmotionType.PRIMITIVE,
        initial_intensity=0.7,
        source_engine=TriggerSource.THOUGHT,
        source_event_id="THOUGHT-01",
        trigger_type="INTELLECTUAL_PUZZLE",
        assessed_significance=0.7,
        perceived_valence=0.6,
        trigger_contribution=0.4,
        mood_contribution=0.2,
        personality_multiplier=1.0,
    )
    assert rec.state == EmotionState.TRIGGERED

    # 1. Valid: TRIGGERED -> ACTIVE_SURGE
    surge = lifecycle_mgr.transition_emotion_state(
        rec.emotion_id,
        new_state=EmotionState.ACTIVE_SURGE,
        triggering_factor="Epistemic interest confirmed",
        intensity_delta=0.1,
    )
    assert surge.state == EmotionState.ACTIVE_SURGE

    # 2. Invalid: ACTIVE_SURGE -> TRIGGERED (illegal backward leap)
    with pytest.raises(InvalidEmotionStateTransitionError):
        lifecycle_mgr.transition_emotion_state(
            rec.emotion_id,
            new_state=EmotionState.TRIGGERED,
            triggering_factor="Illegal back-transition",
        )

    # 3. Valid: ACTIVE_SURGE -> SUSTAINED_DECAY
    decay = lifecycle_mgr.transition_emotion_state(
        rec.emotion_id,
        new_state=EmotionState.SUSTAINED_DECAY,
        triggering_factor="Temporal attenuation commencement",
    )
    assert decay.state == EmotionState.SUSTAINED_DECAY

    # 4. Valid: SUSTAINED_DECAY -> EXTINCTION
    extinct = lifecycle_mgr.transition_emotion_state(
        rec.emotion_id,
        new_state=EmotionState.EXTINCTION,
        triggering_factor="Fading threshold crossed (<0.05)",
    )
    assert extinct.state == EmotionState.EXTINCTION

    # 5. Invalid: EXTINCTION -> ACTIVE_SURGE (terminal state cannot transition)
    with pytest.raises(InvalidEmotionStateTransitionError):
        lifecycle_mgr.transition_emotion_state(
            rec.emotion_id,
            new_state=EmotionState.ACTIVE_SURGE,
            triggering_factor="Illegal revival from extinction",
        )


def test_active_pool_bounds_max_10(lifecycle_mgr, db_factory):
    """Verify active pool bounds (max 10) gracefully retire the oldest/lowest-intensity emotion (E30)."""
    created_ids = []

    # Create 10 active emotions
    for i in range(MAX_ACTIVE_EMOTION_POOL_SIZE):
        rec = lifecycle_mgr.create_emotion(
            category_name="Interest",
            emotion_type=EmotionType.PRIMITIVE,
            initial_intensity=0.2 + (i * 0.05),
            source_engine=TriggerSource.PERCEPTION,
            source_event_id=f"EVT-BULK-{i}",
            trigger_type="INCREMENTAL_STIMULUS",
            assessed_significance=0.5,
            perceived_valence=0.5,
            trigger_contribution=0.3,
            mood_contribution=0.1,
            personality_multiplier=1.0,
        )
        created_ids.append(rec.emotion_id)

    # Put the first emotion into SUSTAINED_DECAY with low intensity so it is the clear retirement candidate
    lifecycle_mgr.transition_emotion_state(
        created_ids[0],
        new_state=EmotionState.ACTIVE_SURGE,
        triggering_factor="Surge",
    )
    lifecycle_mgr.transition_emotion_state(
        created_ids[0],
        new_state=EmotionState.SUSTAINED_DECAY,
        triggering_factor="Decay start",
    )

    # Verify active pool has 10
    active_now = lifecycle_mgr.recover_active_emotions()
    assert len(active_now) == 10

    # Creating the 11th emotion triggers automatic pool bounds enforcement
    rec_11 = lifecycle_mgr.create_emotion(
        category_name="Happiness",
        emotion_type=EmotionType.PRIMITIVE,
        initial_intensity=0.85,
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="EVT-11",
        trigger_type="CAPACITY_TEST",
        assessed_significance=0.85,
        perceived_valence=0.9,
        trigger_contribution=0.5,
        mood_contribution=0.2,
        personality_multiplier=1.0,
    )

    # Pool size must remain <= 10
    active_after = lifecycle_mgr.recover_active_emotions()
    assert len(active_after) == 10

    # The retired emotion must now be in EXTINCTION state
    with db_factory.read_cursor() as cursor:
        cursor.execute(
            "SELECT state FROM emotion_records WHERE emotion_id = ?;",
            (str(created_ids[0]),),
        )
        assert cursor.fetchone()["state"] == "EXTINCTION"

        # Must have been archived to historical events
        cursor.execute(
            "SELECT * FROM emotion_historical_events WHERE emotion_id = ?;",
            (str(created_ids[0]),),
        )
        hist = cursor.fetchone()
        assert hist is not None
        assert hist["resolution_type"] == "OVERWRITTEN"


def test_crash_recovery_from_disk_db(tmp_path):
    """Verify that process restarts and reloads active emotions, mood, and tendencies cleanly from disk."""
    db_file = str(tmp_path / "emotion_test_disk.db")

    # Session 1: Create database and state
    f1 = DatabaseConnectionFactory(db_file)
    r1 = MigrationRunner(f1)
    r1.apply_migrations()
    mgr1 = EmotionalLifecycleManager(f1)

    rec1 = mgr1.create_emotion(
        category_name="Trust",
        emotion_type=EmotionType.PRIMITIVE,
        initial_intensity=0.75,
        source_engine=TriggerSource.SOCIAL,
        source_event_id="SOC-01",
        trigger_type="WARM_GREETING",
        assessed_significance=0.75,
        perceived_valence=0.8,
        trigger_contribution=0.5,
        mood_contribution=0.2,
        personality_multiplier=1.0,
    )
    mgr1.transition_emotion_state(
        rec1.emotion_id,
        new_state=EmotionState.ACTIVE_SURGE,
        triggering_factor="Interpersonal validation",
    )

    # Update mood in Session 1
    with f1.write_transaction() as cursor:
        cursor.execute(
            """
            UPDATE emotion_mood_record
            SET valence = 0.55, arousal = 0.35, dominance = 0.40,
                label_descriptor = 'Warmly Optimistic';
            """
        )

    # Simulate hard crash / shutdown
    f1.close()

    # Session 2: Fresh start pointing to same disk file
    f2 = DatabaseConnectionFactory(db_file)
    mgr2 = EmotionalLifecycleManager(f2)

    # Recover active emotions
    recovered_emotions = mgr2.recover_active_emotions()
    assert len(recovered_emotions) == 1
    assert recovered_emotions[0].emotion_id == rec1.emotion_id
    assert recovered_emotions[0].category_name == "Trust"
    assert recovered_emotions[0].state == EmotionState.ACTIVE_SURGE

    # Recover mood
    recovered_mood = mgr2.recover_current_mood()
    assert recovered_mood.label_descriptor == "Warmly Optimistic"
    assert recovered_mood.valence == 0.55
    assert recovered_mood.arousal == 0.35

    # Recover tendencies
    tendencies = mgr2.recover_tendencies()
    assert "emotion.curiosity_sensitivity" in tendencies
    assert tendencies["emotion.curiosity_sensitivity"].current_value == 1.25

    f2.close()

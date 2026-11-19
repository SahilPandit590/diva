"""
Unit tests for Part 4: 3D Circumplex Mood Manager & Emotional Conflict Manager.
Verifies damped moving average mood integration, single-event delta clamping (<=0.05),
independence of acute emotion vs persistent mood (Axiom 1),
bimodal tension metrics (Delta_tension), and emergent mixed emotion blends (Axiom 2).
"""

from datetime import datetime, timezone
import pytest

from emotion_engine.conflict.manager import EmotionalConflictManager
from emotion_engine.database.connection import DatabaseConnectionFactory
from emotion_engine.database.migrations import MigrationRunner
from emotion_engine.lifecycle.manager import EmotionalLifecycleManager
from emotion_engine.mood.manager import (
    MAX_SINGLE_EVENT_DELTA,
    MoodManager,
)
from emotion_engine.types.enums import (
    ConflictCategory,
    EmotionType,
    TriggerSource,
)


@pytest.fixture
def db_factory():
    factory = DatabaseConnectionFactory(":memory:")
    runner = MigrationRunner(factory)
    runner.apply_migrations()
    yield factory
    factory.close()


@pytest.fixture
def lifecycle_mgr(db_factory):
    return EmotionalLifecycleManager(db_factory)


@pytest.fixture
def mood_mgr(db_factory, lifecycle_mgr):
    return MoodManager(db_factory, lifecycle_mgr)


@pytest.fixture
def conflict_mgr(db_factory, lifecycle_mgr):
    return EmotionalConflictManager(db_factory, lifecycle_mgr)


def test_mood_label_derivation():
    """Verify 3D continuous PAD coordinates map to accurate qualitative labels."""
    derive = MoodManager.derive_mood_label

    # Near origin
    assert derive(0.05, -0.05, 0.00) == "Equanimous Neutral"

    # All positive
    assert derive(0.60, 0.40, 0.50) == "Buoyant Optimism"

    # All negative
    assert derive(-0.60, -0.40, -0.50) == "Reflective Melancholy"

    # High negative valence, high arousal, high dominance
    assert derive(-0.50, 0.60, 0.40) == "Agitated Frustration"

    # Positive valence, low arousal, high dominance
    assert derive(0.70, -0.30, 0.40) == "Serene Tranquility"


def test_mood_integration_damped_average_and_clamping(mood_mgr, lifecycle_mgr, db_factory):
    """Verify mood moving-average integration is damped and single-event delta is clamped <= 0.05 (Phase 4 Gate)."""
    # 1. Initial mood is neutral
    initial_mood = mood_mgr.get_current_mood()
    assert initial_mood.valence == 0.0
    assert initial_mood.label_descriptor == "Equanimous Neutral"

    # 2. Spawn an intense positive emotion: Happiness (V=0.8, A=0.5, D=0.6, I=0.90)
    rec_happy = lifecycle_mgr.create_emotion(
        category_name="Happiness",
        emotion_type=EmotionType.PRIMITIVE,
        initial_intensity=0.90,
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="EVT-CELEBRATION",
        trigger_type="TRIUMPH",
        assessed_significance=0.90,
        perceived_valence=0.90,
        trigger_contribution=0.50,
        mood_contribution=0.20,
        personality_multiplier=1.0,
    )

    # 3. Execute mood integration pass with large elapsed time (e.g. 500 seconds)
    # Even with large elapsed time, single-event delta must NOT exceed MAX_SINGLE_EVENT_DELTA (0.05)
    updated_mood = mood_mgr.update_mood(
        active_emotions=[rec_happy],
        elapsed_seconds=500.0,
    )

    delta_v = abs(updated_mood.valence - initial_mood.valence)
    delta_a = abs(updated_mood.arousal - initial_mood.arousal)
    delta_d = abs(updated_mood.dominance - initial_mood.dominance)

    assert delta_v <= MAX_SINGLE_EVENT_DELTA + 1e-4
    assert delta_a <= MAX_SINGLE_EVENT_DELTA + 1e-4
    assert delta_d <= MAX_SINGLE_EVENT_DELTA + 1e-4
    assert updated_mood.valence > 0.0  # Nudged positively


def test_transient_emotion_within_opposing_mood_independence(mood_mgr, lifecycle_mgr, db_factory):
    """
    Verify Axiom 1 (Emotion is Not Mood & Orthogonal Boundary):
    A sudden joke/happiness surges within a somber mood without erasing the mood.
    """
    # Set background mood to a somber, reflective state (V=-0.70)
    with db_factory.write_transaction() as cursor:
        cursor.execute(
            """
            UPDATE emotion_mood_record
            SET valence = -0.70, arousal = -0.30, dominance = -0.40,
                label_descriptor = 'Reflective Melancholy';
            """
        )

    mood_before = mood_mgr.get_current_mood()
    assert mood_before.valence == -0.70
    assert mood_before.label_descriptor == "Reflective Melancholy"

    # Transient acute trigger: Funny joke triggers acute Happiness (I=0.85)
    rec_joke = lifecycle_mgr.create_emotion(
        category_name="Happiness",
        emotion_type=EmotionType.PRIMITIVE,
        initial_intensity=0.85,
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="EVT-JOKE",
        trigger_type="HUMOROUS_REMARK",
        assessed_significance=0.80,
        perceived_valence=0.85,
        trigger_contribution=0.50,
        mood_contribution=0.15,
        personality_multiplier=1.0,
    )

    # Mood updates slightly with normal elapsed time (1 second)
    mood_after = mood_mgr.update_mood(
        active_emotions=[rec_joke],
        elapsed_seconds=1.0,
    )

    # Acute happiness is fully felt at 0.85
    assert rec_joke.current_intensity == 0.85

    # Background mood remains somber / melancholy, nudged only by ~0.001
    assert mood_after.valence < -0.65
    assert "Melancholy" in mood_after.label_descriptor
    # Both co-exist cleanly without contradiction
    assert rec_joke.current_intensity > 0.80
    assert mood_after.valence < -0.60


def test_emotional_conflict_detection_and_tension(lifecycle_mgr, conflict_mgr, db_factory):
    """
    Verify Axiom 2 (Multiple Emotions Coexist & No Neutral Collapse):
    Happiness and Sadness simultaneously active produce high tension without cancellation.
    """
    # 1. Create co-occurring Happiness (I=0.80) and Sadness (I=0.75) - e.g. Graduation/Farewell
    rec_happy = lifecycle_mgr.create_emotion(
        category_name="Happiness",
        emotion_type=EmotionType.PRIMITIVE,
        initial_intensity=0.80,
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="EVT-GRAD-1",
        trigger_type="ACHIEVEMENT",
        assessed_significance=0.80,
        perceived_valence=0.80,
        trigger_contribution=0.45,
        mood_contribution=0.20,
        personality_multiplier=1.0,
    )
    rec_sad = lifecycle_mgr.create_emotion(
        category_name="Sadness",
        emotion_type=EmotionType.PRIMITIVE,
        initial_intensity=0.75,
        source_engine=TriggerSource.MEMORY,
        source_event_id="EVT-GRAD-2",
        trigger_type="FAREWELL_DEPARTURE",
        assessed_significance=0.75,
        perceived_valence=-0.70,
        trigger_contribution=0.40,
        mood_contribution=0.20,
        personality_multiplier=1.0,
    )

    # 2. Detect conflicts
    conflicts = conflict_mgr.detect_conflicts([rec_happy, rec_sad])
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.conflict_category == ConflictCategory.VALENCE_OPPOSITION
    # Tension = 2.0 * min(0.80, 0.75) * 1.0 = 1.5 -> clamped to 1.0
    assert conflict.tension_metric == 1.0
    assert conflict.is_active is True

    # 3. Overall tension
    overall_tension = conflict_mgr.calculate_overall_emotional_tension([rec_happy, rec_sad])
    # 2.0 * 0.75 * 0.9 = 1.35 -> clamped to 1.0
    assert overall_tension == 1.0

    # 4. Invariant: Neither emotion was canceled or destroyed
    with db_factory.read_cursor() as cursor:
        cursor.execute("SELECT current_intensity FROM emotion_records WHERE emotion_id = ?;", (str(rec_happy.emotion_id),))
        assert cursor.fetchone()["current_intensity"] == 0.80
        cursor.execute("SELECT current_intensity FROM emotion_records WHERE emotion_id = ?;", (str(rec_sad.emotion_id),))
        assert cursor.fetchone()["current_intensity"] == 0.75


def test_mixed_emotion_blend_recognition(lifecycle_mgr, conflict_mgr, db_factory):
    """Verify recognition of canonical emergent mixed blends (e.g. Bittersweetness)."""
    # Create Happiness and Sadness
    rec_happy = lifecycle_mgr.create_emotion(
        category_name="Happiness",
        emotion_type=EmotionType.PRIMITIVE,
        initial_intensity=0.75,
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="EVT-01",
        trigger_type="T1",
        assessed_significance=0.75,
        perceived_valence=0.8,
        trigger_contribution=0.4,
        mood_contribution=0.2,
        personality_multiplier=1.0,
    )
    rec_sad = lifecycle_mgr.create_emotion(
        category_name="Sadness",
        emotion_type=EmotionType.PRIMITIVE,
        initial_intensity=0.70,
        source_engine=TriggerSource.MEMORY,
        source_event_id="EVT-02",
        trigger_type="T2",
        assessed_significance=0.70,
        perceived_valence=-0.7,
        trigger_contribution=0.4,
        mood_contribution=0.2,
        personality_multiplier=1.0,
    )

    blends = conflict_mgr.detect_mixed_blends([rec_happy, rec_sad])
    assert len(blends) == 1
    blend = blends[0]
    assert blend.primary_blend_name == "Bittersweetness"
    assert blend.coherence_score > 0.90  # 0.70 / 0.75 ~ 0.933

    # Verify persisted in database
    with db_factory.read_cursor() as cursor:
        cursor.execute("SELECT * FROM emotion_mixed_states WHERE mixed_state_id = ?;", (str(blend.mixed_state_id),))
        row = cursor.fetchone()
        assert row is not None
        assert row["primary_blend_name"] == "Bittersweetness"

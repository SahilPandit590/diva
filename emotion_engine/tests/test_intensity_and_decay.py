"""
Unit tests for Part 3: Mathematical Intensity & Temporal Decay Engine.
Verifies multi-factor intensity scaling, PAD mood alignment, exponential decay dynamics,
renewal boosts (E14), and extinction pruning at I < 0.05 (E15).
"""

from datetime import datetime, timedelta, timezone
import pytest

from emotion_engine.database.connection import DatabaseConnectionFactory
from emotion_engine.database.migrations import MigrationRunner
from emotion_engine.decay.manager import (
    EmotionTransitionManager,
    FADING_EXTINCTION_THRESHOLD,
)
from emotion_engine.intensity.manager import (
    IntensityManager,
    IntensityTier,
)
from emotion_engine.lifecycle.manager import EmotionalLifecycleManager
from emotion_engine.types.enums import (
    EmotionState,
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
def transition_mgr(db_factory, lifecycle_mgr):
    return EmotionTransitionManager(db_factory, lifecycle_mgr)


def test_intensity_tier_mapping():
    """Verify continuous intensity is mapped cleanly to calibrated qualitative tiers."""
    get_tier = IntensityManager.get_intensity_tier
    assert get_tier(0.00) == IntensityTier.SUB_THRESHOLD
    assert get_tier(0.14) == IntensityTier.SUB_THRESHOLD
    assert get_tier(0.15) == IntensityTier.MILD
    assert get_tier(0.39) == IntensityTier.MILD
    assert get_tier(0.40) == IntensityTier.MODERATE
    assert get_tier(0.69) == IntensityTier.MODERATE
    assert get_tier(0.70) == IntensityTier.STRONG
    assert get_tier(0.89) == IntensityTier.STRONG
    assert get_tier(0.90) == IntensityTier.ACUTE
    assert get_tier(1.00) == IntensityTier.ACUTE


def test_mood_alignment_cosine_space():
    """Verify directional alignment in 3D circumplex PAD space."""
    align = IntensityManager.compute_mood_alignment

    # 1. Identical direction -> Alignment = 1.0
    pad_a = (0.8, 0.6, 0.6)
    pad_b = (0.8, 0.6, 0.6)
    assert align(pad_a, pad_b) == pytest.approx(1.0, abs=1e-4)

    # 2. Opposite direction -> Alignment = 0.0
    pad_opp = (-0.8, -0.6, -0.6)
    assert align(pad_a, pad_opp) == pytest.approx(0.0, abs=1e-4)

    # 3. Orthogonal direction -> Alignment = 0.5
    pad_ortho = (0.0, 1.0, 0.0)
    pad_x = (1.0, 0.0, 0.0)
    assert align(pad_ortho, pad_x) == pytest.approx(0.5, abs=1e-4)

    # 4. Neutral / zero-magnitude mood -> Alignment = 0.5
    assert align(pad_a, (0.0, 0.0, 0.0)) == 0.5


def test_intensity_calculation_formula():
    """Verify multi-factor intensity formulation: I = clamp(0.55*S + 0.25*Mood + 0.20*Personality)."""
    # High significance (0.9), neutral mood, baseline personality (1.0)
    res = IntensityManager.calculate_intensity(
        category_name="Happiness",
        assessed_significance=0.90,
        current_mood_pad=(0.8, 0.5, 0.6),  # Aligned mood
        personality_multiplier=1.2,
    )
    # Trigger: 0.55 * 0.90 = 0.495
    # Mood: 0.25 * ~1.0 = ~0.25
    # Personality: 0.20 * (1.2 / 2.0) = 0.12
    # Total ~ 0.865
    assert 0.85 <= res["calibrated_intensity"] <= 0.88
    assert res["trigger_contribution"] == pytest.approx(0.495, abs=1e-3)
    assert res["calibrated_intensity"] <= 1.0


def test_exponential_decay_mathematics():
    """Verify exponential half-life decay formulation: I(t) = I_0 * 2^(-t / tau)."""
    compute_decay = EmotionTransitionManager.compute_decayed_intensity

    i_0 = 0.80
    tau = 180.0  # 3 minutes (Anger / Fear)

    # At t = 0 -> I = 0.80
    assert compute_decay(i_0, 0.0, tau) == 0.80

    # At t = tau (180s) -> I = 0.40
    assert compute_decay(i_0, 180.0, tau) == pytest.approx(0.40, abs=1e-4)

    # At t = 2 * tau (360s) -> I = 0.20
    assert compute_decay(i_0, 360.0, tau) == pytest.approx(0.20, abs=1e-4)

    # At t = 3 * tau (540s) -> I = 0.10
    assert compute_decay(i_0, 540.0, tau) == pytest.approx(0.10, abs=1e-4)


def test_renewal_boost_mechanic(lifecycle_mgr, transition_mgr, db_factory):
    """Verify that a matching stimulus boosts active emotion without duplicate spawning (E14)."""
    # 1. Create active emotion
    rec = lifecycle_mgr.create_emotion(
        category_name="Happiness",
        emotion_type=EmotionType.PRIMITIVE,
        initial_intensity=0.60,
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="EVT-ORIGIN",
        trigger_type="COMPLIMENT",
        assessed_significance=0.60,
        perceived_valence=0.8,
        trigger_contribution=0.33,
        mood_contribution=0.15,
        personality_multiplier=1.0,
    )
    # Move to SUSTAINED_DECAY
    lifecycle_mgr.transition_emotion_state(
        rec.emotion_id,
        new_state=EmotionState.ACTIVE_SURGE,
        triggering_factor="Surge",
    )
    lifecycle_mgr.transition_emotion_state(
        rec.emotion_id,
        new_state=EmotionState.SUSTAINED_DECAY,
        triggering_factor="Decay start",
    )

    # 2. Matching stimulus arrives: Apply renewal boost of +0.30
    renewed = transition_mgr.renew_emotion(
        emotion_id=rec.emotion_id,
        boost_delta=0.30,
    )

    # Intensity increased from 0.60 to 0.90
    assert renewed.current_intensity == pytest.approx(0.90, abs=1e-4)
    # State reset to ACTIVE_SURGE
    assert renewed.state == EmotionState.ACTIVE_SURGE

    # Total active emotion count in database remains exactly 1 (no duplicate spawned)
    with db_factory.read_cursor() as cursor:
        cursor.execute("SELECT count(*) as cnt FROM emotion_records WHERE state != 'EXTINCTION';")
        assert cursor.fetchone()["cnt"] == 1


def test_decay_tick_runner_and_extinction(lifecycle_mgr, transition_mgr, db_factory):
    """Verify periodic decay tick attenuates emotions and prunes to EXTINCTION at I < 0.05 (E15)."""
    t_start = datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc)

    # Create acute reflex: Surprise (half-life = 15s) at mild intensity 0.15
    rec = lifecycle_mgr.create_emotion(
        category_name="Surprise",
        emotion_type=EmotionType.PRIMITIVE,
        initial_intensity=0.15,
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="EVT-SURPRISE",
        trigger_type="SUDDEN_SOUND",
        assessed_significance=0.20,
        perceived_valence=0.0,
        trigger_contribution=0.10,
        mood_contribution=0.05,
        personality_multiplier=1.0,
    )
    # Put into ACTIVE_SURGE
    rec_surge = lifecycle_mgr.transition_emotion_state(
        rec.emotion_id,
        new_state=EmotionState.ACTIVE_SURGE,
        triggering_factor="Startle",
    )
    t_start = rec_surge.last_renewed_at

    # 1. Decay tick at t = +15 seconds (1 half-life): I = 0.15 * 0.5 = 0.075 >= 0.05
    t_15s = t_start + timedelta(seconds=15)
    res_1 = transition_mgr.decay_active_emotions(current_time=t_15s)
    assert res_1.active_after_count == 1
    assert res_1.extinct_count == 0

    with db_factory.read_cursor() as cursor:
        cursor.execute("SELECT current_intensity, state FROM emotion_records WHERE emotion_id = ?;", (str(rec.emotion_id),))
        row1 = cursor.fetchone()
        assert row1["current_intensity"] == pytest.approx(0.075, abs=1e-3)
        # Surge window (10s) expired, state shifted to SUSTAINED_DECAY
        assert row1["state"] == "SUSTAINED_DECAY"

    # 2. Decay tick at t = +45 seconds (3 half-lives from start): I = 0.15 * 0.125 = 0.01875 < 0.05
    t_45s = t_start + timedelta(seconds=45)
    res_2 = transition_mgr.decay_active_emotions(current_time=t_45s)
    assert res_2.extinct_count == 1
    assert res_2.active_after_count == 0

    # Emotion must be in EXTINCTION state
    with db_factory.read_cursor() as cursor:
        cursor.execute("SELECT state FROM emotion_records WHERE emotion_id = ?;", (str(rec.emotion_id),))
        assert cursor.fetchone()["state"] == "EXTINCTION"

        # Archived to historical events
        cursor.execute("SELECT * FROM emotion_historical_events WHERE emotion_id = ?;", (str(rec.emotion_id),))
        hist = cursor.fetchone()
        assert hist is not None
        assert hist["category"] == "Surprise"
        assert hist["resolution_type"] == "NATURAL_DECAY"

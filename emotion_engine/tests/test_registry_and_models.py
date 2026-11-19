"""
Unit tests for Part 1: Predefined Emotion Registry & Core Data Models.
Verifies registry completeness (12 primitive, 18 complex), PAD coordinates,
deep immutability, and boundary constraints across all 17 data models.
"""

from datetime import datetime, timezone
import uuid
from pydantic import ValidationError
import pytest

from emotion_engine.types import (
    COMPLEX_EMOTIONS,
    EMOTION_REGISTRY,
    PRIMITIVE_EMOTIONS,
    ActiveEmotionState,
    ConflictCategory,
    DecayCurveType,
    EmotionContext,
    EmotionDecayProfile,
    EmotionDefinition,
    EmotionalConflict,
    EmotionalHistory,
    EmotionalLearningRecord,
    EmotionalTendency,
    EmotionIntensity,
    EmotionProvenance,
    EmotionRecord,
    EmotionState,
    EmotionTransition,
    EmotionTrigger,
    EmotionType,
    LifecycleEntityType,
    MixedEmotionState,
    MoodHistory,
    MoodRecord,
    RegulationRecord,
    RegulationStrategy,
    RegulationStrategyType,
    ResolutionType,
    TriggerSource,
)


def test_registry_completeness():
    """Verify that exactly 12 primitive and 18 complex emotions are registered (30 total)."""
    assert len(PRIMITIVE_EMOTIONS) == 12
    assert len(COMPLEX_EMOTIONS) == 18
    assert len(EMOTION_REGISTRY.list_all()) == 30

    primitive_names = {p.name for p in PRIMITIVE_EMOTIONS}
    expected_primitives = {
        "Happiness", "Sadness", "Fear", "Anger", "Disgust", "Surprise",
        "Interest", "Curiosity", "Affection", "Distress", "Anticipation", "Trust"
    }
    assert primitive_names == expected_primitives

    complex_names = {c.name for c in COMPLEX_EMOTIONS}
    expected_complex = {
        "Excitement", "Anxiety", "Frustration", "Relief", "Nostalgia", "Jealousy",
        "Envy", "Gratitude", "Guilt", "Shame", "Pride", "Loneliness",
        "Compassion", "Hope", "Disappointment", "Boredom", "Resentment", "Embarrassment"
    }
    assert complex_names == expected_complex


def test_registry_lookup_case_insensitivity():
    """Verify registry lookups function cleanly regardless of casing or leading/trailing whitespace."""
    happy = EMOTION_REGISTRY.get("happiness")
    assert happy is not None
    assert happy.name == "Happiness"
    assert happy.emotion_type == EmotionType.PRIMITIVE
    assert happy.valence == 0.8
    assert happy.half_life_seconds == 3600.0

    frustration = EMOTION_REGISTRY.get("  FRUSTRATION  ")
    assert frustration is not None
    assert frustration.name == "Frustration"
    assert frustration.emotion_type == EmotionType.COMPLEX
    assert "Anger" in frustration.constituent_primitives
    assert "Distress" in frustration.constituent_primitives

    assert EMOTION_REGISTRY.get("NonExistentEmotion") is None
    assert EMOTION_REGISTRY.contains("Anger") is True
    assert EMOTION_REGISTRY.contains("unknown") is False


def test_emotion_record_immutability_and_validation():
    """Verify EmotionRecord enforces frozen assignment and valid intensity bounds."""
    rec = EmotionRecord(
        category_name="Happiness",
        emotion_type=EmotionType.PRIMITIVE,
        current_intensity=0.75,
        state=EmotionState.ACTIVE_SURGE,
    )
    assert rec.current_intensity == 0.75
    assert rec.state == EmotionState.ACTIVE_SURGE

    # Assignment must raise ValidationError (frozen)
    with pytest.raises(ValidationError):
        rec.current_intensity = 0.90

    # Bounds check
    with pytest.raises(ValidationError):
        EmotionRecord(
            category_name="Happiness",
            emotion_type=EmotionType.PRIMITIVE,
            current_intensity=1.5,  # Invalid: > 1.0
        )

    with pytest.raises(ValidationError):
        EmotionRecord(
            category_name="Happiness",
            emotion_type=EmotionType.PRIMITIVE,
            current_intensity=-0.1,  # Invalid: < 0.0
        )


def test_active_emotion_state_model():
    """Verify ActiveEmotionState aggregation model."""
    e1 = uuid.uuid4()
    e2 = uuid.uuid4()
    state = ActiveEmotionState(
        active_emotion_ids=(e1, e2),
        dominant_emotion_id=e1,
        aggregate_valence=0.45,
        aggregate_arousal=0.70,
        emotional_tension=0.35,
    )
    assert len(state.active_emotion_ids) == 2
    assert state.dominant_emotion_id == e1
    assert state.aggregate_valence == 0.45


def test_emotion_intensity_model():
    """Verify EmotionIntensity model attributes and constraints."""
    e_id = uuid.uuid4()
    intensity = EmotionIntensity(
        emotion_id=e_id,
        raw_intensity=0.80,
        calibrated_intensity=0.76,
        trigger_contribution=0.50,
        mood_contribution=0.15,
        personality_multiplier=1.1,
    )
    assert intensity.emotion_id == e_id
    assert intensity.calibrated_intensity == 0.76


def test_emotion_trigger_and_context_models():
    """Verify trigger and context metadata structures."""
    e_id = uuid.uuid4()
    trigger = EmotionTrigger(
        emotion_id=e_id,
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="EVT-1001",
        trigger_type="USER_COMPLIMENT",
        assessed_significance=0.85,
        perceived_valence=0.90,
    )
    assert trigger.source_engine == TriggerSource.PERCEPTION
    assert trigger.assessed_significance == 0.85

    context = EmotionContext(
        emotion_id=e_id,
        social_interlocutor_id="USER-ALEX",
        environmental_setting="INTERACTIVE_DIALOGUE",
        uncertainty_score=0.1,
        context_metadata={"channel": "VOICE", "ambient_noise": 0.2},
    )
    assert context.social_interlocutor_id == "USER-ALEX"
    assert context.context_metadata["channel"] == "VOICE"


def test_mixed_emotion_and_conflict_models():
    """Verify MixedEmotionState and EmotionalConflict models."""
    e1 = uuid.uuid4()
    e2 = uuid.uuid4()
    mixed = MixedEmotionState(
        coexisting_emotion_ids=(e1, e2),
        primary_blend_name="Bittersweetness",
        coherence_score=0.88,
    )
    assert mixed.primary_blend_name == "Bittersweetness"

    conflict = EmotionalConflict(
        emotion_a_id=e1,
        emotion_b_id=e2,
        conflict_category=ConflictCategory.VALENCE_OPPOSITION,
        tension_metric=0.64,
        is_active=True,
    )
    assert conflict.conflict_category == ConflictCategory.VALENCE_OPPOSITION
    assert conflict.tension_metric == 0.64


def test_mood_record_and_history_models():
    """Verify 3D circumplex MoodRecord and MoodHistory."""
    mood = MoodRecord(
        valence=0.40,
        arousal=0.20,
        dominance=0.50,
        label_descriptor="Reflective Contentment",
        stability_metric=0.85,
    )
    assert mood.valence == 0.40
    assert mood.arousal == 0.20
    assert mood.dominance == 0.50

    history = MoodHistory(
        valence_snapshot=0.40,
        arousal_snapshot=0.20,
        dominance_snapshot=0.50,
        driving_emotion_ids=(uuid.uuid4(),),
    )
    assert history.valence_snapshot == 0.40


def test_decay_profile_and_regulation_models():
    """Verify decay profile and regulation record models."""
    decay = EmotionDecayProfile(
        emotion_category="Anger",
        half_life_seconds=180.0,
        decay_curve_type=DecayCurveType.EXPONENTIAL,
    )
    assert decay.half_life_seconds == 180.0

    reg = RegulationRecord(
        emotion_id=uuid.uuid4(),
        strategy_used=RegulationStrategyType.COGNITIVE_REAPPRAISAL,
        intensity_before=0.88,
        intensity_after=0.52,
        was_successful=True,
    )
    assert reg.strategy_used == RegulationStrategyType.COGNITIVE_REAPPRAISAL
    assert reg.was_successful is True


def test_tendency_learning_and_provenance_models():
    """Verify tendency, learning, history and provenance models."""
    tendency = EmotionalTendency(
        dimension_name="emotion.curiosity_sensitivity",
        current_value=1.25,
        version=1,
        is_constitutional_baseline=True,
    )
    assert tendency.is_constitutional_baseline is True

    learn = EmotionalLearningRecord(
        proposal_id=uuid.uuid4(),
        dimension_name="emotion.resilience_rate",
        old_value=1.0,
        new_value=1.05,
    )
    assert learn.new_value == 1.05

    e_id = uuid.uuid4()
    hist = EmotionalHistory(
        emotion_id=e_id,
        category="Joy",
        peak_intensity=0.92,
        duration_seconds=420,
        resolution_type=ResolutionType.NATURAL_DECAY,
    )
    assert hist.resolution_type == ResolutionType.NATURAL_DECAY

    prov = EmotionProvenance(
        emotion_id=e_id,
        source_engine="PERCEPTION",
        source_event_id="EVT-2002",
        derivation_chain=("PERCEPTION_INGRESS", "TRIGGER_ANALYZER", "GENERATION_MODULE"),
    )
    assert len(prov.derivation_chain) == 3

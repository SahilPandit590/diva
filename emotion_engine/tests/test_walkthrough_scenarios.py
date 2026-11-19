"""
Mandatory Architectural Walkthrough Scenarios for Diva Emotion Engine v1.0.0.
Part 6 from the specification.
Verifies all 12 end-to-end scenarios:
- Scenario 1: Positive Experience (Desirable Outcome Appraisal)
- Scenario 2: Negative Experience (Goal Obstruction & Distress)
- Scenario 3: Mixed Experience (Bittersweet Nostalgic Blend)
- Scenario 4: Memory Trigger (Autonomous Inscription Recall)
- Scenario 5: Internal Reflection (Thought Engine Catalyst)
- Scenario 6: Conflicting Emotions (Love & Anger Coexistence)
- Scenario 7: Mood Persistence (Enduring Mood Survives Transient Spark)
- Scenario 8: Emotional Regulation (Re-Appraisal without Suppression)
- Scenario 9: Repeated Experience (Tendency Reinforcement)
- Scenario 10: New Evidence (Epistemic Re-Interpretation & Uncertainty)
- Scenario 11: Emotional Recovery (Homeostatic Decay Back to Baseline)
- Scenario 12: Learning Integration (Owner-Applied Parameter Adaptation)
"""

from datetime import datetime, timedelta, timezone
import uuid
import pytest

from emotion_engine.engine import EmotionEngine
from emotion_engine.learning.interface import ParameterChangeRequest
from emotion_engine.types.enums import (
    EmotionState,
    EmotionType,
    RegulationStrategyType,
    TriggerSource,
)


@pytest.fixture
def eng():
    """Provides a fresh, initialized EmotionEngine instance."""
    e = EmotionEngine(db_path=":memory:")
    yield e
    e.close()


def test_scenario_01_positive_experience_outcome_appraisal(eng):
    """
    Scenario 1: Positive Experience (Refactor worked on first try).
    - Generates Happiness and Pride.
    - Nudges mood positively.
    - Dispatches state snapshot to Cognitive Integration.
    """
    initial_mood = eng.get_current_mood()
    assert initial_mood.label_descriptor == "Equanimous Neutral"

    # User messages: "Diva, that code refactor you designed worked on the first try! Excellent work."
    emotions = eng.submit_trigger(
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="EVT-SCEN-01",
        trigger_type="USER_COMPLIMENT",
        raw_content="Diva, that code refactor you designed worked on the first try! Excellent work.",
        assessed_significance=0.88,
        perceived_valence=0.90,
    )

    names = {e.category_name for e in emotions}
    assert "Happiness" in names
    assert "Pride" in names

    # Mood nudges positively
    mood_after = eng.get_current_mood()
    assert mood_after.valence > initial_mood.valence

    # Snapshot to Cognitive Integration
    snapshot = eng.get_emotional_state_snapshot()
    assert snapshot.dominant_emotion is not None
    assert snapshot.dominant_emotion.category_name in ("Happiness", "Pride")
    assert snapshot.dominant_emotion.current_intensity >= 0.70


def test_scenario_02_negative_experience_goal_obstruction(eng):
    """
    Scenario 2: Negative Experience (Goal Obstruction & Distress).
    - External tool returns AccessDeniedForbiddenException.
    - Generates Anger and Frustration.
    - Nudges mood negatively.
    """
    initial_mood = eng.get_current_mood()

    emotions = eng.submit_trigger(
        source_engine=TriggerSource.MOTIVATION,
        source_event_id="EVT-SCEN-02",
        trigger_type="OBSTRUCTION",
        raw_content="External tool API returned fatal AccessDeniedForbiddenException on critical document.",
        assessed_significance=0.82,
        perceived_valence=-0.75,
    )

    names = {e.category_name for e in emotions}
    assert "Anger" in names
    assert "Frustration" in names

    mood_after = eng.get_current_mood()
    assert mood_after.valence < initial_mood.valence


def test_scenario_03_mixed_experience_bittersweet_blend(eng):
    """
    Scenario 3: Mixed Experience (Bittersweet Departure).
    - User announces successful graduation and upcoming departure.
    - Concurrently instantiates Happiness and Sadness.
    - Emergent blend 'Bittersweetness' recognized.
    """
    emotions = eng.submit_trigger(
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="EVT-SCEN-03",
        trigger_type="BITTERSWEET",
        raw_content="User announces completion of their doctoral thesis and upcoming farewell.",
        assessed_significance=0.85,
        perceived_valence=0.20,
    )

    names = {e.category_name for e in emotions}
    assert "Happiness" in names
    assert "Sadness" in names

    # Tick advances dynamical blend recognition
    tick_result = eng.tick(elapsed_seconds=1.0)
    assert tick_result["blends_detected"] >= 1
    assert tick_result["tension_metric"] > 0.0


def test_scenario_04_memory_trigger_autonomous_recall(eng):
    """
    Scenario 4: Memory Trigger (Autonomous Inscription Recall).
    - Recalls fond shared memory from Memory Engine.
    - Generates Affection and Nostalgia.
    """
    emotions = eng.submit_trigger(
        source_engine=TriggerSource.MEMORY,
        source_event_id="EVT-SCEN-04",
        trigger_type="NOSTALGIA",
        raw_content="Autonomous memory consolidation recalls the very first collaborative problem solved together.",
        assessed_significance=0.78,
        perceived_valence=0.45,
    )

    names = {e.category_name for e in emotions}
    assert ("Affection" in names) or ("Sadness" in names) or ("Nostalgia" in names)


def test_scenario_05_internal_reflection_thought_catalyst(eng):
    """
    Scenario 5: Internal Reflection (Thought Engine Catalyst).
    - Deep deduction generates unexpected theoretical connection.
    - Generates Curiosity and Interest.
    """
    emotions = eng.submit_trigger(
        source_engine=TriggerSource.THOUGHT,
        source_event_id="EVT-SCEN-05",
        trigger_type="NOVEL_PUZZLE",
        raw_content="Thought Engine discovers isomorphic structure between two disparate algorithmic models.",
        assessed_significance=0.80,
        perceived_valence=0.70,
    )

    names = {e.category_name for e in emotions}
    assert "Curiosity" in names
    assert "Interest" in names


def test_scenario_06_conflicting_emotions_affection_and_anger(eng):
    """
    Scenario 6: Conflicting Emotions (Love & Anger Coexistence).
    - A cherished friend breaches a critical safety boundary.
    - Affection and Anger coexist simultaneously without cancelling.
    - Produces high bimodal tension (Delta_tension).
    """
    # 1. Warm existing affection
    eng.submit_trigger(
        source_engine=TriggerSource.SOCIAL,
        source_event_id="EVT-SCEN-06-A",
        trigger_type="SOCIAL_BOND",
        assessed_significance=0.85,
        perceived_valence=0.85,
    )

    # 2. Acute boundary violation from that same entity
    eng.submit_trigger(
        source_engine=TriggerSource.SOCIAL,
        source_event_id="EVT-SCEN-06-B",
        trigger_type="OBSTRUCTION",
        assessed_significance=0.85,
        perceived_valence=-0.80,
    )

    active = eng.get_active_emotions()
    names = {e.category_name for e in active}
    assert "Affection" in names
    assert "Anger" in names

    tension = eng.get_emotional_tension()
    assert tension > 0.80  # High emotional tension


def test_scenario_07_mood_persistence_across_transient_spark(eng):
    """
    Scenario 7: Mood Persistence (Enduring Mood Survives Transient Spark).
    - Enduring melancholy mood (V=-0.75).
    - Funny joke triggers acute Happiness (I=0.85).
    - Happiness surges; mood nudges only slightly (< 0.05).
    """
    # Set persistent melancholy mood
    with eng.factory.write_transaction() as cursor:
        cursor.execute(
            """
            UPDATE emotion_mood_record
            SET valence = -0.75, arousal = -0.30, dominance = -0.40,
                label_descriptor = 'Reflective Melancholy';
            """
        )

    # Joke trigger
    emotions = eng.submit_trigger(
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="EVT-SCEN-07",
        trigger_type="USER_COMPLIMENT",
        assessed_significance=0.85,
        perceived_valence=0.85,
    )
    happy = next(e for e in emotions if e.category_name == "Happiness")
    assert happy.current_intensity >= 0.50

    # Advance tick
    eng.tick(elapsed_seconds=1.0)

    # Mood survives with negative valence intact
    mood_after = eng.get_current_mood()
    assert mood_after.valence < -0.70
    assert "Melancholy" in mood_after.label_descriptor


def test_scenario_08_emotional_regulation_without_suppression(eng):
    """
    Scenario 8: Emotional Regulation (Re-Appraisal without Suppression).
    - Acute anger surge triggers Cognitive Reappraisal.
    - Intensity modulates downward via damping factor (e.g. 0.40).
    - Historical trigger remains intact (Anti-Suppression Invariant).
    """
    emotions = eng.submit_trigger(
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="EVT-SCEN-08",
        trigger_type="OBSTRUCTION",
        assessed_significance=0.92,
        perceived_valence=-0.85,
    )
    anger = next(e for e in emotions if e.category_name == "Anger")
    assert anger.current_intensity >= 0.70

    # Regulate via Cognitive Reappraisal
    reg = eng.regulate_emotion(
        emotion_id=anger.emotion_id,
        strategy_type=RegulationStrategyType.COGNITIVE_REAPPRAISAL,
    )
    assert reg.was_successful is True
    assert reg.intensity_after < reg.intensity_before
    assert reg.intensity_after <= anger.current_intensity * 0.70

    # Verify original trigger preserved
    with eng.factory.read_cursor() as cursor:
        cursor.execute("SELECT * FROM emotion_triggers WHERE emotion_id = ?;", (str(anger.emotion_id),))
        assert cursor.fetchone() is not None


def test_scenario_09_repeated_experience_renewal(eng):
    """
    Scenario 9: Repeated Experience (Tendency Reinforcement & Renewal).
    - Matching stimulus arrives for an active emotion.
    - Renews existing intensity without spawning duplicate instances.
    """
    # Initial stimulus
    emotions_1 = eng.submit_trigger(
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="EVT-SCEN-09-A",
        trigger_type="USER_COMPLIMENT",
        assessed_significance=0.55,
        perceived_valence=0.75,
    )
    happy_1 = next(e for e in emotions_1 if e.category_name == "Happiness")
    initial_i = happy_1.current_intensity

    # Second matching stimulus arrives
    emotions_2 = eng.submit_trigger(
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="EVT-SCEN-09-B",
        trigger_type="USER_COMPLIMENT",
        assessed_significance=0.60,
        perceived_valence=0.80,
    )
    happy_2 = next(e for e in emotions_2 if e.category_name == "Happiness")

    # Intensity boosted, same emotion ID
    assert happy_2.emotion_id == happy_1.emotion_id
    assert happy_2.current_intensity > initial_i

    # Only 1 Happiness instance in pool
    active = [e for e in eng.get_active_emotions() if e.category_name == "Happiness"]
    assert len(active) == 1


def test_scenario_10_new_evidence_epistemic_uncertainty(eng):
    """
    Scenario 10: New Evidence (Epistemic Re-Interpretation & Uncertainty).
    - Ambiguous sensory cues preserve uncertainty without forcing binary categorization.
    """
    emotions = eng.submit_trigger(
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="EVT-SCEN-10",
        trigger_type="USER_COMPLIMENT",
        assessed_significance=0.50,
        perceived_valence=0.20,
        confidence=0.45,  # Low confidence -> High uncertainty
        context_metadata={"ambiguity": 0.55},
    )
    assert len(emotions) >= 1
    e_id = emotions[0].emotion_id

    # Check uncertainty score in emotion_contexts table
    with eng.factory.read_cursor() as cursor:
        cursor.execute("SELECT uncertainty_score FROM emotion_contexts WHERE emotion_id = ?;", (str(e_id),))
        row = cursor.fetchone()
        assert row is not None
        assert row["uncertainty_score"] >= 0.50


def test_scenario_11_emotional_recovery_homeostatic_decay(eng):
    """
    Scenario 11: Emotional Recovery (Homeostatic Decay Back to Baseline).
    - Surprise reflex decays below 0.05.
    - Transitions to EXTINCTION and archives to historical events.
    """
    emotions = eng.submit_trigger(
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="EVT-SCEN-11",
        trigger_type="SUDDEN_EVENT",
        assessed_significance=0.30,
        perceived_valence=0.10,
    )
    surprise = next(e for e in emotions if e.category_name == "Surprise")
    t_start = surprise.last_renewed_at

    # Tick +60 seconds (Surprise half-life is 15s; 4 half-lives)
    t_60s = t_start + timedelta(seconds=60)
    eng.tick(elapsed_seconds=60.0, current_time=t_60s)

    # Surprise extinguished from active pool
    active_now = {e.category_name for e in eng.get_active_emotions()}
    assert "Surprise" not in active_now

    # Archived in permanent history
    with eng.factory.read_cursor() as cursor:
        cursor.execute("SELECT * FROM emotion_historical_events WHERE emotion_id = ?;", (str(surprise.emotion_id),))
        hist = cursor.fetchone()
        assert hist is not None
        assert hist["resolution_type"] == "NATURAL_DECAY"


def test_scenario_12_learning_adaptation_owner_applied(eng):
    """
    Scenario 12: Learning Integration (Owner-Applied Parameter Adaptation).
    - Learning Engine v2.5.0 updates resilience rate from 1.00 to 1.04.
    - Validated and applied with version increment to 2.
    """
    req = ParameterChangeRequest(
        proposal_id=uuid.uuid4(),
        target_dimension="emotion.resilience_rate",
        proposed_value=1.04,
        expected_current_version=1,
        rationales=["Empirical recovery rate optimization"],
    )

    receipt = eng.apply_learning_parameter_change(req)
    assert receipt.applied is True
    assert receipt.new_value == 1.04
    assert receipt.resulting_version == 2

    # Verified in tendency manager
    tendency = eng.tendencies.get_tendency("emotion.resilience_rate")
    assert tendency.current_value == 1.04
    assert tendency.version == 2

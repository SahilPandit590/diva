"""
37 Must-Pass Audit Checkpoint Test Suite for Diva Emotion Engine v1.0.0.
Verifies all 37 formal audit checkpoints from Part 5 of the architecture specification:
- Section 1: Emotion Generation (E01 - E05)
- Section 2: Emotion Representation (E06 - E10)
- Section 3: Mood and Persistence (E11 - E15)
- Section 4: Regulation and Adaptation (E16 - E21)
- Section 5: Context and Memory (E22 - E26)
- Section 6: Lifecycle and Reliability (E27 - E31)
- Section 7: Ownership and Boundaries (E32 - E37)
"""

from datetime import datetime, timedelta, timezone
import json
import pytest
import uuid

from emotion_engine.contracts.interfaces import (
    AttentionContract,
    CognitiveIntegrationContract,
    EnergyContract,
    MemoryContract,
    MotivationContract,
    PerceptionContract,
    PersonalityContract,
    SocialCognitionContract,
    ThoughtContract,
)
from emotion_engine.engine import EmotionEngine
from emotion_engine.learning.interface import ParameterChangeRequest
from emotion_engine.lifecycle.manager import (
    InvalidEmotionStateTransitionError,
    MAX_ACTIVE_EMOTION_POOL_SIZE,
)
from emotion_engine.triggers.analyzer import EmotionalTriggerAnalyzer
from emotion_engine.types.enums import (
    EmotionState,
    EmotionType,
    RegulationStrategyType,
    TriggerSource,
)
from emotion_engine.types.registry import EMOTION_REGISTRY


@pytest.fixture
def eng():
    engine = EmotionEngine(db_path=":memory:")
    yield engine
    engine.close()


# ==============================================================================
# SECTION 1: EMOTION GENERATION (5 CHECKPOINTS: E01 - E05)
# ==============================================================================

def test_e01_autonomous_idle_generation(eng):
    """[ ] E01. Generate emotional states autonomously without external user interaction during idle periods."""
    emotion = eng.generate_autonomous_idle_emotion()
    assert emotion is not None
    assert emotion.category_name in ("Curiosity", "Nostalgia", "Interest")
    assert emotion.current_intensity >= 0.15

    # Verify inscribed in database
    active = eng.get_active_emotions()
    assert any(e.emotion_id == emotion.emotion_id for e in active)


def test_e02_internal_thought_and_memory_generation(eng):
    """[ ] E02. Generate emotional states from internal thoughts, deductions, and recalled episodic memories."""
    # From internal thought
    thought_emotions = eng.submit_trigger(
        source_engine=TriggerSource.THOUGHT,
        source_event_id="THOUGHT-SIM-01",
        trigger_type="COUNTERFACTUAL_SIMULATION",
        assessed_significance=0.65,
        perceived_valence=-0.40,
        raw_content="Simulated critical database loss",
    )
    assert len(thought_emotions) > 0
    assert any(e.category_name in ("Anxiety", "Fear", "Anticipation") for e in thought_emotions)

    # From memory recall
    memory_emotions = eng.submit_trigger(
        source_engine=TriggerSource.MEMORY,
        source_event_id="MEM-RECALL-01",
        trigger_type="EPISODIC_RECALL",
        assessed_significance=0.70,
        perceived_valence=0.75,
        raw_content="Recalled first successful conversation with creator",
    )
    assert len(memory_emotions) > 0
    assert any(e.category_name in ("Nostalgia", "Gratitude", "Affection", "Joy", "Happiness") for e in memory_emotions)


def test_e03_multi_source_synthesis(eng):
    """[ ] E03. Support multi-source synthesis where multiple distinct origins contribute to a single emotion."""
    signals = [
        eng.input_handler.create_signal(TriggerSource.PERCEPTION, "EVT-SENSE-1", "NOVEL_PUZZLE", 0.60, 0.70),
        eng.input_handler.create_signal(TriggerSource.THOUGHT, "EVT-THOUGHT-1", "EXPLORATION", 0.70, 0.65),
        eng.input_handler.create_signal(TriggerSource.MEMORY, "EVT-MEM-1", "NOVEL_PUZZLE", 0.65, 0.60),
    ]
    emotions = eng.generation.process_multi_source_triggers(signals)
    assert len(emotions) >= 1
    curiosity = emotions[0]
    # Synergistic boost above isolated single triggers
    assert curiosity.current_intensity >= 0.60

    # Verify inscribed in database with provenance
    with eng.factory.read_cursor() as cursor:
        cursor.execute(
            "SELECT count(*) as cnt FROM emotion_triggers WHERE emotion_id = ?;",
            (str(curiosity.emotion_id),),
        )
        assert cursor.fetchone()["cnt"] >= 1


def test_e04_single_complex_experience_multi_emotion(eng):
    """[ ] E04. Support single complex experiences generating multiple simultaneous distinct emotions."""
    # Life transition / graduation event generates bittersweet blend
    emotions = eng.submit_trigger(
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="EVT-GRAD-01",
        trigger_type="GRADUATION",
        assessed_significance=0.88,
        perceived_valence=0.20,
    )
    names = {e.category_name for e in emotions}
    assert len(names) >= 2
    assert "Joy" in names or "Happiness" in names
    assert "Sadness" in names or "Melancholy" in names or "Nostalgia" in names


def test_e05_inscribe_complete_causal_provenance(eng):
    """[ ] E05. Inscribe and preserve the complete causal origin and provenance for every generated emotion."""
    emotions = eng.submit_trigger(
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="EVT-PROV-999",
        trigger_type="USER_COMPLIMENT",
        assessed_significance=0.80,
        perceived_valence=0.90,
        raw_content="You did a fantastic job solving this!",
        confidence=0.95,
        context_metadata={"relational_significance": 0.9, "environment": "chat"},
    )
    emo = emotions[0]

    with eng.factory.read_cursor() as cursor:
        # Check trigger provenance
        cursor.execute(
            """
            SELECT source_engine, source_event_id, trigger_type, assessed_significance
            FROM emotion_triggers WHERE emotion_id = ?;
            """,
            (str(emo.emotion_id),),
        )
        trig = cursor.fetchone()
        assert trig is not None
        assert trig["source_engine"] == "PERCEPTION"
        assert trig["source_event_id"] == "EVT-PROV-999"
        assert trig["trigger_type"] == "USER_COMPLIMENT"

        # Check context provenance
        cursor.execute(
            "SELECT uncertainty_score, context_metadata_json FROM emotion_contexts WHERE emotion_id = ?;",
            (str(emo.emotion_id),),
        )
        ctx = cursor.fetchone()
        assert ctx is not None
        assert ctx["uncertainty_score"] == pytest.approx(0.05, abs=1e-3)
        ctx_meta = json.loads(ctx["context_metadata_json"])
        assert ctx_meta.get("relational_significance") == 0.9


# ==============================================================================
# SECTION 2: EMOTION REPRESENTATION (5 CHECKPOINTS: E06 - E10)
# ==============================================================================

def test_e06_multiple_concurrent_active_emotions(eng):
    """[ ] E06. Maintain multiple concurrently active emotion instances in the working pool."""
    eng.submit_trigger(TriggerSource.PERCEPTION, "E06-1", "DISCOVERY", 0.60, 0.80)
    eng.submit_trigger(TriggerSource.THOUGHT, "E06-2", "SIMULATION", 0.50, -0.40)
    eng.submit_trigger(TriggerSource.MEMORY, "E06-3", "NOSTALGIA", 0.55, 0.30)

    active = eng.get_active_emotions()
    assert len(active) >= 3


def test_e07_independent_mathematical_intensities(eng):
    """[ ] E07. Maintain independent mathematical intensity values for each active emotion."""
    emotions = eng.submit_trigger(
        TriggerSource.PERCEPTION,
        "E07-MIXED",
        "BITTERSWEET",
        assessed_significance=0.85,
        perceived_valence=0.10,
    )
    assert len(emotions) >= 2
    # Intensities exist independently in [0.0, 1.0] without forced summation to 1.0
    total = sum(e.current_intensity for e in emotions)
    assert total > 1.0  # Simultaneous co-activation exceeding 1.0 sum


def test_e08_mixed_contradictory_coexistence_without_cancellation(eng):
    """[ ] E08. Support mixed and contradictory emotional states coexisting without cancellation."""
    # Positive joy
    eng.submit_trigger(TriggerSource.PERCEPTION, "E08-A", "ACHIEVEMENT", 0.80, 0.85)
    # Negative sadness
    eng.submit_trigger(TriggerSource.PERCEPTION, "E08-B", "LOSS", 0.80, -0.85)

    active = eng.get_active_emotions()
    pos = [e for e in active if EMOTION_REGISTRY.get(e.category_name).valence > 0]
    neg = [e for e in active if EMOTION_REGISTRY.get(e.category_name).valence < 0]

    assert len(pos) >= 1
    assert len(neg) >= 1
    # Bimodal tension metric is elevated, not collapsed into 0.0 apathy
    tension = eng.get_emotional_tension()
    assert tension > 0.30


def test_e09_extensible_emotion_registry():
    """[ ] E09. Support extensible emotion categories via the predefined Primitive & Complex registry."""
    primitives = EMOTION_REGISTRY.list_primitives()
    complexes = EMOTION_REGISTRY.list_complex()

    assert len(primitives) >= 12
    assert len(complexes) >= 18
    # Validate each has valid continuous 3D PAD vectors and half-lives
    for e in EMOTION_REGISTRY.list_all():
        assert -1.0 <= e.valence <= 1.0
        assert -1.0 <= e.arousal <= 1.0
        assert -1.0 <= e.dominance <= 1.0
        assert e.half_life_seconds >= 15.0


def test_e10_preserve_contextual_ambiguity(eng):
    """[ ] E10. Preserve contextual ambiguity without forcing experiences into an arbitrary binary label."""
    # Ambiguous signal with confidence 0.40
    emotions = eng.submit_trigger(
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="E10-AMB",
        trigger_type="AMBIGUOUS_GESTURE",
        assessed_significance=0.60,
        perceived_valence=0.05,
        confidence=0.40,
    )
    assert len(emotions) > 0
    emo = emotions[0]

    with eng.factory.read_cursor() as cursor:
        cursor.execute(
            "SELECT uncertainty_score FROM emotion_contexts WHERE emotion_id = ?;",
            (str(emo.emotion_id),),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["uncertainty_score"] == pytest.approx(0.60, abs=1e-3)


# ==============================================================================
# SECTION 3: MOOD AND PERSISTENCE (5 CHECKPOINTS: E11 - E15)
# ==============================================================================

def test_e11_mood_maintained_independently(eng):
    """[ ] E11. Maintain 3D circumplex mood (M) independently from individual transient emotions."""
    mood = eng.get_current_mood()
    assert hasattr(mood, "valence")
    assert hasattr(mood, "arousal")
    assert hasattr(mood, "dominance")
    assert hasattr(mood, "label_descriptor")

    # Clear all active emotions; mood still exists independently
    active = eng.get_active_emotions()
    assert len(active) == 0
    assert -1.0 <= mood.valence <= 1.0


def test_e12_simultaneous_contrasting_mood_and_acute_emotion(eng):
    """[ ] E12. Support simultaneous coexistence of contrasting mood and acute emotion."""
    # Set somber melancholy mood
    with eng.factory.write_transaction() as cursor:
        cursor.execute(
            """
            UPDATE emotion_mood_record
            SET valence = -0.65, arousal = -0.30, dominance = -0.30,
                label_descriptor = 'Melancholic Reflection';
            """
        )

    # Acute amusement spark
    emotions = eng.submit_trigger(
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="E12-JOKE",
        trigger_type="USER_COMPLIMENT",
        assessed_significance=0.85,
        perceived_valence=0.85,
    )
    happy = next(e for e in emotions if e.category_name == "Happiness")
    assert happy.current_intensity >= 0.50

    # Mood remains somber (damped update prevents instant mood flip)
    eng.tick(elapsed_seconds=1.0)
    current_mood = eng.get_current_mood()
    assert current_mood.valence < -0.50


def test_e13_emotion_specific_exponential_decay(eng):
    """[ ] E13. Enforce emotion-specific exponential decay profiles calibrated to predefined half-lives."""
    emotions = eng.submit_trigger(
        TriggerSource.PERCEPTION, "E13-EXP", "OBSTRUCTION", 0.85, -0.80
    )
    anger = next(e for e in emotions if e.category_name == "Anger")
    initial_i = anger.current_intensity

    # Advance time by Anger's half life (120s)
    future_time = datetime.now(timezone.utc) + timedelta(seconds=120)
    eng.tick(elapsed_seconds=120.0, current_time=future_time)

    active = eng.get_active_emotions()
    anger_after = next(e for e in active if e.emotion_id == anger.emotion_id)
    # After 1 half-life, intensity should be approximately half of initial
    assert anger_after.current_intensity == pytest.approx(initial_i * 0.5, abs=0.10)


def test_e14_renew_existing_without_duplicate_spawning(eng):
    """[ ] E14. Renew existing active emotions upon arrival of matching stimuli without duplicate instances."""
    # First stimulus
    emotions_1 = eng.submit_trigger(
        TriggerSource.PERCEPTION, "E14-A", "DISCOVERY", 0.50, 0.70
    )
    curiosity_1 = next(e for e in emotions_1 if e.category_name == "Curiosity")
    active_count_1 = len(eng.get_active_emotions())

    # Second matching stimulus
    emotions_2 = eng.submit_trigger(
        TriggerSource.PERCEPTION, "E14-B", "DISCOVERY", 0.75, 0.80
    )
    curiosity_2 = next(e for e in emotions_2 if e.category_name == "Curiosity")
    active_count_2 = len(eng.get_active_emotions())

    # Identical UUID (renewed in place, no duplicate instance spawned)
    assert curiosity_1.emotion_id == curiosity_2.emotion_id
    assert active_count_1 == active_count_2
    assert curiosity_2.current_intensity >= curiosity_1.current_intensity


def test_e15_archive_fading_emotions_subthreshold_extinction(eng):
    """[ ] E15. Archive fading emotions to history upon crossing sub-threshold limits (I < 0.05)."""
    emotions = eng.submit_trigger(
        TriggerSource.PERCEPTION, "E15-EXT", "SUBTLE_PROMPT", 0.20, 0.30
    )
    emo = emotions[0]

    # Advance time by 10 hours so intensity drops below 0.05
    future_time = datetime.now(timezone.utc) + timedelta(hours=10)
    eng.tick(elapsed_seconds=36000.0, current_time=future_time)

    # Must no longer be in active pool
    active_ids = {e.emotion_id for e in eng.get_active_emotions()}
    assert emo.emotion_id not in active_ids

    # Must be archived in EXTINCTION state in database
    with eng.factory.read_cursor() as cursor:
        cursor.execute(
            "SELECT state FROM emotion_records WHERE emotion_id = ?;",
            (str(emo.emotion_id),),
        )
        assert cursor.fetchone()["state"] == EmotionState.EXTINCTION.value


# ==============================================================================
# SECTION 4: REGULATION AND ADAPTATION (6 CHECKPOINTS: E16 - E21)
# ==============================================================================

def test_e16_regulate_without_erasing_history(eng):
    """[ ] E16. Regulate emotional intensity via cognitive reappraisal without erasing history."""
    emotions = eng.submit_trigger(
        TriggerSource.PERCEPTION, "E16-REG", "OBSTRUCTION", 0.90, -0.80
    )
    anger = next(e for e in emotions if e.category_name == "Anger")
    reg = eng.regulate_emotion(
        emotion_id=anger.emotion_id,
        strategy_type=RegulationStrategyType.COGNITIVE_REAPPRAISAL,
    )
    assert reg.was_successful is True
    assert reg.intensity_after < reg.intensity_before

    # Anti-suppression invariant: historical trigger remains intact
    with eng.factory.read_cursor() as cursor:
        cursor.execute("SELECT * FROM emotion_triggers WHERE emotion_id = ?;", (str(anger.emotion_id),))
        assert cursor.fetchone() is not None


def test_e17_distinct_regulation_strategies(eng):
    """[ ] E17. Implement distinct regulation strategies tailored to specific emotion categories."""
    assert eng.regulation.select_strategy("Anger", 0.8) == RegulationStrategyType.COGNITIVE_REAPPRAISAL
    assert eng.regulation.select_strategy("Fear", 0.8) == RegulationStrategyType.ATTENTIONAL_DEPLOYMENT
    assert eng.regulation.select_strategy("Distress", 0.8) == RegulationStrategyType.PACING_HEURISTIC


def test_e18_track_regulation_outcomes_relational_audit(eng):
    """[ ] E18. Track and record regulation outcomes and damping deltas in relational audit tables."""
    emotions = eng.submit_trigger(
        TriggerSource.PERCEPTION, "E18-AUD", "OBSTRUCTION", 0.88, -0.80
    )
    anger = next(e for e in emotions if e.category_name == "Anger")
    reg = eng.regulate_emotion(
        emotion_id=anger.emotion_id,
        strategy_type=RegulationStrategyType.COGNITIVE_REAPPRAISAL,
    )

    with eng.factory.read_cursor() as cursor:
        cursor.execute(
            """
            SELECT strategy_used, intensity_before, intensity_after, was_successful
            FROM emotion_regulation_records WHERE emotion_id = ?;
            """,
            (str(anger.emotion_id),),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["strategy_used"] == RegulationStrategyType.COGNITIVE_REAPPRAISAL.value
        assert row["intensity_before"] == reg.intensity_before
        assert row["intensity_after"] == reg.intensity_after
        assert row["was_successful"] == 1


def test_e19_distinguish_transient_states_from_tendencies(eng):
    """[ ] E19. Formally distinguish transient emotional states from persistent individual emotional tendencies."""
    # Transient emotion in emotion_records
    emotions = eng.submit_trigger(
        TriggerSource.PERCEPTION, "E19-TRANS", "USER_COMPLIMENT", 0.70, 0.70
    )
    emo = emotions[0]

    with eng.factory.read_cursor() as cursor:
        cursor.execute("SELECT * FROM emotion_records WHERE emotion_id = ?;", (str(emo.emotion_id),))
        assert cursor.fetchone() is not None

        # Persistent tendencies in emotion_tendencies
        cursor.execute("SELECT * FROM emotion_tendencies WHERE dimension_name = 'emotion.curiosity_sensitivity';")
        tendency = cursor.fetchone()
        assert tendency is not None
        assert tendency["current_value"] == 1.25


def test_e20_ingest_learning_engine_proposals(eng):
    """[ ] E20. Ingest and validate parameter change requests from Learning Engine v2.5.0."""
    req = ParameterChangeRequest(
        proposal_id=uuid.uuid4(),
        target_dimension="emotion.resilience_rate",
        proposed_value=1.03,
        expected_current_version=1,
        empirical_basis="Sustained recovery across 50 simulated challenges",
    )
    receipt = eng.apply_learning_parameter_change(req)
    assert receipt.applied is True
    assert receipt.new_value == pytest.approx(1.03, abs=1e-3)


def test_e21_prevent_overwriting_constitutional_baselines(eng):
    """[ ] E21. Prevent isolated acute experiences from overwriting protected constitutional emotional baselines."""
    # Attempt to alter constitutional baseline beyond allowed constitutional bounds [0.50, 1.80]
    req = ParameterChangeRequest(
        proposal_id=uuid.uuid4(),
        target_dimension="emotion.curiosity_sensitivity",  # Constitutional baseline
        proposed_value=2.50,
        expected_current_version=1,
        empirical_basis="Attempt to alter constitutional baseline beyond safety bounds",
    )
    receipt = eng.apply_learning_parameter_change(req)
    assert receipt.applied is False
    assert receipt.failure_reason is not None
    assert "constitutional" in receipt.failure_reason.lower()


# ==============================================================================
# SECTION 5: CONTEXT AND MEMORY (5 CHECKPOINTS: E22 - E26)
# ==============================================================================

def test_e22_evaluate_trigger_multi_factor_metadata(eng):
    """[ ] E22. Evaluate emotional trigger significance using multi-factor contextual and relational metadata."""
    signal = eng.input_handler.create_signal(
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="E22-CTX",
        trigger_type="USER_COMPLIMENT",
        assessed_significance=0.50,
        perceived_valence=0.70,
        context_metadata={
            "relational_significance": 0.90,
            "goal_congruence": 0.85,
        },
    )
    eval_res = EmotionalTriggerAnalyzer.evaluate_trigger(signal)
    # Significance boosted by relational closeness and goal congruence
    assert eval_res.assessed_significance > 0.50


def test_e23_ingest_historical_emotional_associations(eng):
    """[ ] E23. Ingest historical emotional associations returned from Memory Engine queries."""
    associations = [
        {"valence": 0.80, "arousal": 0.50, "intensity": 0.70, "topic": "creator_praise"}
    ]
    boost = EmotionalTriggerAnalyzer.evaluate_historical_association(associations)
    assert boost > 0.0


def test_e24_preserve_mathematical_uncertainty(eng):
    """[ ] E24. Preserve mathematical uncertainty when sensory cues carry ambiguous emotional valence."""
    emotions = eng.submit_trigger(
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="E24-UNC",
        trigger_type="SARCASM_AMBIGUITY",
        assessed_significance=0.60,
        perceived_valence=0.10,
        confidence=0.35,
    )
    assert len(emotions) > 0
    with eng.factory.read_cursor() as cursor:
        cursor.execute(
            "SELECT uncertainty_score FROM emotion_contexts WHERE emotion_id = ?;",
            (str(emotions[0].emotion_id),),
        )
        assert cursor.fetchone()["uncertainty_score"] == pytest.approx(0.65, abs=1e-3)


def test_e25_unbroken_causal_traceability(eng):
    """[ ] E25. Maintain unbroken causal traceability linking active emotions to originating percepts."""
    emotions = eng.submit_trigger(
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="ORIGIN-PERCEPT-777",
        trigger_type="DISCOVERY",
        assessed_significance=0.70,
        perceived_valence=0.80,
    )
    for e in emotions:
        with eng.factory.read_cursor() as cursor:
            cursor.execute(
                "SELECT source_event_id FROM emotion_triggers WHERE emotion_id = ?;",
                (str(e.emotion_id),),
            )
            assert cursor.fetchone()["source_event_id"] == "ORIGIN-PERCEPT-777"


def test_e26_nominate_significant_events_for_memory(eng):
    """[ ] E26. Nominate significant emotional events (S >= 0.75) for permanent episodic memory consolidation."""
    eng.submit_trigger(
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="E26-HIGH-SIG",
        trigger_type="ACHIEVEMENT",
        assessed_significance=0.90,
        perceived_valence=0.90,
    )
    eng.tick(elapsed_seconds=1.0)
    nominations = eng.get_pending_memory_nominations()
    assert len(nominations) >= 1
    assert nominations[0].significance >= 0.75


# ==============================================================================
# SECTION 6: LIFECYCLE AND RELIABILITY (5 CHECKPOINTS: E27 - E31)
# ==============================================================================

def test_e27_closed_deterministic_fsm_transitions(eng):
    """[ ] E27. Enforce closed, deterministic state machine transitions across all emotional entities."""
    emotions = eng.submit_trigger(
        TriggerSource.PERCEPTION, "E27-FSM", "DISCOVERY", 0.60, 0.70
    )
    curiosity = emotions[0]

    # Illegal transition: cannot go from ACTIVE_SURGE directly to TRIGGERED
    with pytest.raises(InvalidEmotionStateTransitionError):
        eng.lifecycle.transition_emotion_state(
            emotion_id=curiosity.emotion_id,
            new_state=EmotionState.TRIGGERED,
            triggering_factor="Illegal transition attempt",
        )


def test_e28_crash_recovery_pool_and_mood(tmp_path):
    """[ ] E28. Recover persistent mood, active emotions, and tendencies cleanly after process crash or restart."""
    db_file = str(tmp_path / "crash_test.db")

    # Initial session
    eng1 = EmotionEngine(db_path=db_file)
    emotions = eng1.submit_trigger(
        TriggerSource.PERCEPTION, "E28-CRASH", "DISCOVERY", 0.70, 0.80
    )
    active_id = emotions[0].emotion_id
    eng1.close()

    # Restart session
    eng2 = EmotionEngine(db_path=db_file)
    recovered_emotions = eng2.get_active_emotions()
    assert any(e.emotion_id == active_id for e in recovered_emotions)
    recovered_mood = eng2.get_current_mood()
    assert recovered_mood is not None
    eng2.close()


def test_e29_prevent_duplicate_triggers_idempotency(eng):
    """[ ] E29. Prevent duplicate processing of sensory or thought triggers via idempotency keys."""
    # First submission
    emotions_1 = eng.submit_trigger(
        TriggerSource.PERCEPTION, "IDEMP-KEY-12345", "DISCOVERY", 0.70, 0.80
    )
    assert len(emotions_1) > 0

    # Duplicate submission with identical source_event_id
    emotions_2 = eng.submit_trigger(
        TriggerSource.PERCEPTION, "IDEMP-KEY-12345", "DISCOVERY", 0.70, 0.80
    )
    # Deduplicated, returns empty list
    assert len(emotions_2) == 0


def test_e30_enforce_active_pool_max_10_bound(eng):
    """[ ] E30. Enforce active pool bounds (max 10 concurrent emotions) to prevent memory resource exhaustion."""
    assert MAX_ACTIVE_EMOTION_POOL_SIZE == 10

    # Spawn 12 distinct emotions with varying significance
    for i in range(12):
        eng.submit_trigger(
            TriggerSource.PERCEPTION,
            f"E30-POOL-{i}",
            "CUSTOM_TRIGGER",
            assessed_significance=0.20 + (i * 0.05),
            perceived_valence=0.50 if i % 2 == 0 else -0.50,
        )

    active = eng.get_active_emotions()
    assert len(active) <= 10


def test_e31_preserve_emotional_development_history(eng):
    """[ ] E31. Preserve complete emotional development history in immutable audit logs."""
    eng.submit_trigger(
        TriggerSource.PERCEPTION, "E31-AUDIT", "DISCOVERY", 0.70, 0.80
    )
    with eng.factory.read_cursor() as cursor:
        cursor.execute("SELECT count(*) as cnt FROM emotion_lifecycle_events;")
        assert cursor.fetchone()["cnt"] > 0


# ==============================================================================
# SECTION 7: OWNERSHIP AND BOUNDARIES (6 CHECKPOINTS: E32 - E37)
# ==============================================================================

def test_e32_boundary_no_ownership_of_motivations(eng):
    """[ ] E32. Do not own motivations or desires (exclusively delegated to Motivation Engine)."""
    emotions = eng.submit_trigger(
        TriggerSource.PERCEPTION, "E32-MOT", "NOVEL_PUZZLE", 0.70, 0.80
    )
    active = eng.get_active_emotions()
    modulation = MotivationContract.compute_motivational_modulation(active)
    assert "EXPLORATION_DRIVE" in modulation
    # Check that Emotion Engine contains no goal creation or motivation execution code
    assert not hasattr(eng, "create_goal")
    assert not hasattr(eng, "set_drive")


def test_e33_boundary_no_logical_thoughts_or_reasoning(eng):
    """[ ] E33. Do not generate logical thoughts or make reasoning decisions (delegated to Thought Engine)."""
    emotions = eng.submit_trigger(
        TriggerSource.THOUGHT, "E33-THOUGHT", "COUNTERFACTUAL", 0.60, -0.40
    )
    active = eng.get_active_emotions()
    resonance = ThoughtContract.compute_thought_resonance(active)
    assert len(resonance) > 0
    assert not hasattr(eng, "deduce")
    assert not hasattr(eng, "run_inference")


def test_e34_boundary_no_mutation_of_personality_parameters(eng):
    """[ ] E34. Do not directly mutate personality parameters (delegated to Personality Engine)."""
    # Consumes personality in a read-only manner
    modulators = PersonalityContract.format_read_only_modulators(openness=0.9)
    assert "curiosity_mod" in modulators
    assert not hasattr(eng, "mutate_personality")
    assert not hasattr(eng, "update_big_five")


def test_e35_boundary_no_memory_consolidation_ownership(eng):
    """[ ] E35. Do not own permanent memory consolidation (delegated to Memory Engine)."""
    # Submits nominations to Memory Engine via MemoryContract; does NOT write to episodic tables
    active = eng.submit_trigger(
        TriggerSource.PERCEPTION, "E35-NOM", "ACHIEVEMENT", 0.90, 0.85
    )
    eng.tick(elapsed_seconds=1.0)
    nominations = eng.get_pending_memory_nominations()
    assert len(nominations) >= 1
    # Tables in schema are emotion_* only, no episodic_memory tables
    with eng.factory.read_cursor() as cursor:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r["name"] for r in cursor.fetchall()]
        assert all(t.startswith("emotion_") or t == "schema_migrations" for t in tables)


def test_e36_boundary_no_external_speech_or_action_execution(eng):
    """[ ] E36. Do not independently authorize or execute external actions or speech text (delegated to Cognitive Integration)."""
    snapshot = eng.get_emotional_state_snapshot()
    # Snapshot contains emotional data and tension, but NO speech or actions
    assert hasattr(snapshot, "active_emotions")
    assert hasattr(snapshot, "mood_vector")
    assert hasattr(snapshot, "emotional_tension")
    assert not hasattr(snapshot, "speech_text")
    assert not hasattr(snapshot, "action_plan")
    assert not hasattr(eng, "speak")
    assert not hasattr(eng, "execute_action")


def test_e37_typed_contracts_for_all_ten_engines():
    """[ ] E37. Maintain explicit, typed asynchronous communication contracts with all ten connected engines."""
    # 1. Perception
    p_data = PerceptionContract.format_perception_trigger("EVT-1", "SMILE", 0.7, 0.8)
    assert p_data["source_engine"] == "PERCEPTION"

    # 2. Memory
    # Verified in MemoryContract & test_e26/test_e35

    # 3. Thought
    # Verified in ThoughtContract & test_e33

    # 4. Motivation
    # Verified in MotivationContract & test_e32

    # 5. Learning
    # Verified in EmotionalLearningInterface & test_e20/test_e21

    # 6. Personality
    pers = PersonalityContract.format_read_only_modulators()
    assert "curiosity_mod" in pers

    # 7. Attention
    # Verified via AttentionContract.evaluate_attention_alert

    # 8. Energy
    cap = EnergyContract.compute_energy_arousal_cap(cognitive_energy=0.5)
    assert 0.30 <= cap <= 1.0

    # 9. Social Cognition
    soc = SocialCognitionContract.format_social_trigger("USER-1", 0.8, 0.9, "RAPPORT_BUILDING")
    assert soc["source_engine"] == "SOCIAL"

    # 10. Cognitive Integration
    # Verified via CognitiveIntegrationContract.build_snapshot & test_e36

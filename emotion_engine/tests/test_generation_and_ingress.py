"""
Unit tests for Part 5: Ingress Gateway, Trigger Analyzer & Emotion Generation Module.
Verifies:
- Autonomous idle generation (E01)
- Generation from thoughts and memories (E02)
- Multi-source convergence synthesis (E03)
- Single experience generating multiple simultaneous emotions (E04)
- Complete causal provenance tracking (E05)
- Idempotency and deduplication (E29)
"""

import json
import pytest

from emotion_engine.database.connection import DatabaseConnectionFactory
from emotion_engine.database.migrations import MigrationRunner
from emotion_engine.decay.manager import EmotionTransitionManager
from emotion_engine.generation.classifier import EmotionClassificationModule
from emotion_engine.generation.module import EmotionGenerationModule
from emotion_engine.ingress.handler import (
    EmotionInputHandler,
    EmotionTriggerSignal,
)
from emotion_engine.lifecycle.manager import EmotionalLifecycleManager
from emotion_engine.mood.manager import MoodManager
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
def mood_mgr(db_factory, lifecycle_mgr):
    return MoodManager(db_factory, lifecycle_mgr)


@pytest.fixture
def transition_mgr(db_factory, lifecycle_mgr):
    return EmotionTransitionManager(db_factory, lifecycle_mgr)


@pytest.fixture
def gen_module(db_factory, lifecycle_mgr, mood_mgr, transition_mgr):
    return EmotionGenerationModule(
        factory=db_factory,
        lifecycle=lifecycle_mgr,
        mood=mood_mgr,
        transitions=transition_mgr,
    )


def test_autonomous_idle_emotion_generation(gen_module, db_factory):
    """Verify autonomous emotional emergence during idle periods without external user input (E01)."""
    idle_emotion = gen_module.generate_autonomous_idle_emotion()
    assert idle_emotion is not None
    assert idle_emotion.state == EmotionState.ACTIVE_SURGE
    assert idle_emotion.category_name in ("Curiosity", "Nostalgia", "Interest")

    # Verify recorded in database with SPONTANEOUS trigger
    with db_factory.read_cursor() as cursor:
        cursor.execute("SELECT * FROM emotion_triggers WHERE emotion_id = ?;", (str(idle_emotion.emotion_id),))
        trig = cursor.fetchone()
        assert trig is not None
        assert trig["source_engine"] == TriggerSource.SPONTANEOUS.value
        assert "IDLE" in trig["trigger_type"]


def test_internal_thought_and_memory_triggers(gen_module):
    """Verify generation from internal reflections (Thought) and recalled memories (E02)."""
    # 1. Thought Engine deduction
    thought_sig = EmotionInputHandler.create_signal(
        source_engine=TriggerSource.THOUGHT,
        source_event_id="THOUGHT-REFLECT-01",
        trigger_type="NOVEL_PUZZLE",
        raw_content="Deep deduction reveals an unexpected architectural symmetry.",
        assessed_significance=0.75,
        perceived_valence=0.70,
    )
    thought_emotions = gen_module.process_trigger_signal(thought_sig)
    assert len(thought_emotions) >= 1
    assert thought_emotions[0].category_name in ("Curiosity", "Interest")

    # 2. Memory Engine episodic recall
    mem_sig = EmotionInputHandler.create_signal(
        source_engine=TriggerSource.MEMORY,
        source_event_id="MEM-RECALL-99",
        trigger_type="NOSTALGIA",
        raw_content="Recalled an earlier shared victory with the user.",
        assessed_significance=0.80,
        perceived_valence=0.40,
    )
    mem_emotions = gen_module.process_trigger_signal(mem_sig)
    assert len(mem_emotions) >= 1
    categories = {e.category_name for e in mem_emotions}
    assert ("Sadness" in categories) or ("Affection" in categories) or ("Nostalgia" in categories)


def test_multi_source_convergence_synthesis(gen_module):
    """Verify simultaneous multi-source triggers synthesize an amplified composite emotion (E03)."""
    sig1 = EmotionInputHandler.create_signal(
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="PERC-01",
        trigger_type="USER_COMPLIMENT",
        assessed_significance=0.60,
        perceived_valence=0.80,
    )
    sig2 = EmotionInputHandler.create_signal(
        source_engine=TriggerSource.MEMORY,
        source_event_id="MEM-01",
        trigger_type="ACHIEVEMENT",
        assessed_significance=0.50,
        perceived_valence=0.80,
    )

    # Multi-source synthesis
    composite_results = gen_module.process_multi_source_triggers([sig1, sig2])
    assert len(composite_results) >= 1
    assert composite_results[0].current_intensity >= 0.50


def test_single_experience_multi_emotion_generation(gen_module):
    """Verify single experience generates multiple simultaneous distinct emotions (E04)."""
    # Major achievement trigger (assessed significance >= 0.85)
    sig = EmotionInputHandler.create_signal(
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="EVT-TRIUMPH-100",
        trigger_type="ACHIEVEMENT",
        raw_content="Diva solved the complex multi-threaded concurrency deadlock.",
        assessed_significance=0.88,
        perceived_valence=0.90,
    )
    results = gen_module.process_trigger_signal(sig)

    # Must generate both primary (Happiness) and secondary (Pride)
    assert len(results) >= 2
    names = {r.category_name for r in results}
    assert "Happiness" in names
    assert "Pride" in names


def test_causal_provenance_preservation(gen_module, db_factory):
    """Verify unbroken causal derivation chain is inscribed for every generated emotion (E05)."""
    sig = EmotionInputHandler.create_signal(
        source_engine=TriggerSource.SOCIAL,
        source_event_id="SOC-RAPPORT-01",
        trigger_type="SOCIAL_BOND",
        assessed_significance=0.75,
        perceived_valence=0.85,
    )
    results = gen_module.process_trigger_signal(sig)
    assert len(results) >= 1
    e_id = results[0].emotion_id

    with db_factory.read_cursor() as cursor:
        cursor.execute("SELECT * FROM emotion_provenance WHERE emotion_id = ?;", (str(e_id),))
        prov = cursor.fetchone()
        assert prov is not None
        assert prov["source_engine"] == "SOCIAL"
        assert prov["source_event_id"] == "SOC-RAPPORT-01"
        chain = json.loads(prov["derivation_chain_json"])
        assert len(chain) >= 3
        assert "SOCIAL_INGRESS" in chain[0]


def test_idempotency_deduplication(gen_module):
    """Verify submitting the same event ID twice is ignored without duplicate processing (E29)."""
    sig = EmotionInputHandler.create_signal(
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="IDEMPOTENT-EVT-01",
        trigger_type="USER_COMPLIMENT",
        assessed_significance=0.70,
        perceived_valence=0.75,
    )
    first_pass = gen_module.process_trigger_signal(sig)
    assert len(first_pass) >= 1

    # Second pass with identical source_event_id
    second_pass = gen_module.process_trigger_signal(sig)
    assert len(second_pass) == 0  # Deduplicated, no new processing

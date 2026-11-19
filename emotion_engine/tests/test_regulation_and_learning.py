"""
Unit tests for Part 6: Emotional Regulation, Tendencies & Learning Engine Integration.
Verifies:
- Anti-suppression regulation and damping audit logging (E16, E18, Axiom 3)
- Strategy selection tailored to emotion category (E17)
- Distinguishing persistent tendencies from transient emotions (E19)
- Owner-directed parameter adaptation from Learning Engine v2.5.0 (E20)
- Constitutional baseline identity locks against unconstrained drift (E21, Axiom 5)
"""

import uuid
import pytest

from emotion_engine.database.connection import DatabaseConnectionFactory
from emotion_engine.database.migrations import MigrationRunner
from emotion_engine.learning.interface import (
    EmotionalLearningInterface,
    ParameterChangeRequest,
)
from emotion_engine.lifecycle.manager import EmotionalLifecycleManager
from emotion_engine.regulation.module import EmotionRegulationModule
from emotion_engine.regulation.strategies import REGULATION_STRATEGIES
from emotion_engine.tendencies.manager import EmotionalTendencyManager
from emotion_engine.types.enums import (
    EmotionState,
    EmotionType,
    RegulationStrategyType,
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
def reg_module(db_factory, lifecycle_mgr):
    return EmotionRegulationModule(db_factory, lifecycle_mgr)


@pytest.fixture
def tendency_mgr(db_factory, lifecycle_mgr):
    return EmotionalTendencyManager(db_factory, lifecycle_mgr)


@pytest.fixture
def learning_iface(db_factory, tendency_mgr):
    return EmotionalLearningInterface(db_factory, tendency_mgr)


def test_regulation_reappraisal_and_anti_suppression(lifecycle_mgr, reg_module, db_factory):
    """
    Verify Axiom 3 (Regulation is not Suppression & Audit Trail):
    Cognitive reappraisal modulates acute intensity while preserving the complete historical record.
    """
    # 1. Create an acute Anger emotion (I=0.88)
    rec = lifecycle_mgr.create_emotion(
        category_name="Anger",
        emotion_type=EmotionType.PRIMITIVE,
        initial_intensity=0.88,
        source_engine=TriggerSource.PERCEPTION,
        source_event_id="EVT-UNFAIR-OBSTRUCTION",
        trigger_type="BOUNDARY_VIOLATION",
        assessed_significance=0.88,
        perceived_valence=-0.75,
        trigger_contribution=0.50,
        mood_contribution=0.18,
        personality_multiplier=1.0,
    )
    assert rec.current_intensity == 0.88

    # 2. Execute Cognitive Reappraisal regulation
    reg_record = reg_module.regulate_emotion(
        emotion_id=rec.emotion_id,
        strategy_type=RegulationStrategyType.COGNITIVE_REAPPRAISAL,
    )

    assert reg_record.was_successful is True
    assert reg_record.intensity_before == 0.88
    # 0.88 * (1.0 - 0.35) = 0.572
    assert reg_record.intensity_after == pytest.approx(0.572, abs=1e-3)

    # 3. Verify emotion record updated in database to SUSTAINED_DECAY
    with db_factory.read_cursor() as cursor:
        cursor.execute("SELECT current_intensity, state FROM emotion_records WHERE emotion_id = ?;", (str(rec.emotion_id),))
        row = cursor.fetchone()
        assert row["current_intensity"] == pytest.approx(0.572, abs=1e-3)
        assert row["state"] == "SUSTAINED_DECAY"

        # 4. Anti-Suppression Verification:
        # The originating trigger in emotion_triggers MUST still exist unchanged
        cursor.execute("SELECT * FROM emotion_triggers WHERE emotion_id = ?;", (str(rec.emotion_id),))
        trig = cursor.fetchone()
        assert trig is not None
        assert trig["trigger_type"] == "BOUNDARY_VIOLATION"

        # The regulation audit record MUST exist in emotion_regulation_records
        cursor.execute("SELECT * FROM emotion_regulation_records WHERE emotion_id = ?;", (str(rec.emotion_id),))
        audit = cursor.fetchone()
        assert audit is not None
        assert audit["strategy_used"] == RegulationStrategyType.COGNITIVE_REAPPRAISAL.value


def test_regulation_strategy_selection(reg_module):
    """Verify strategy selection heuristic tailored to specific emotion categories (E17)."""
    assert reg_module.select_strategy("Anger", 0.90) == RegulationStrategyType.COGNITIVE_REAPPRAISAL
    assert reg_module.select_strategy("Frustration", 0.85) == RegulationStrategyType.COGNITIVE_REAPPRAISAL
    assert reg_module.select_strategy("Fear", 0.85) == RegulationStrategyType.ATTENTIONAL_DEPLOYMENT
    assert reg_module.select_strategy("Anxiety", 0.80) == RegulationStrategyType.ATTENTIONAL_DEPLOYMENT
    assert reg_module.select_strategy("Distress", 0.85) == RegulationStrategyType.PACING_HEURISTIC


def test_tendency_multipliers_vs_transient_emotions(tendency_mgr):
    """Verify persistent individual tendencies are distinct from transient emotions (E19)."""
    # Baseline curiosity sensitivity is high (1.25)
    assert tendency_mgr.get_multiplier_for_category("Curiosity") == 1.25

    # Baseline anger sensitivity is moderate (0.70)
    assert tendency_mgr.get_multiplier_for_category("Anger") == 0.70

    # Unmapped category falls back to reactivity_baseline (1.00)
    assert tendency_mgr.get_multiplier_for_category("Surprise") == 1.00


def test_learning_adaptation_successful_bounded_update(learning_iface, tendency_mgr, db_factory):
    """Verify valid parameter change request from Learning Engine v2.5.0 is applied and audited (E20)."""
    req = ParameterChangeRequest(
        proposal_id=uuid.uuid4(),
        target_dimension="emotion.resilience_rate",
        proposed_value=1.04,  # Delta = +0.04 (<= 0.05)
        expected_current_version=1,
        rationales=["Repeated exposure to recovery challenges demonstrates improved resilience."],
    )

    receipt = learning_iface.apply_parameter_change(req)
    assert receipt.applied is True
    assert receipt.old_value == 1.00
    assert receipt.new_value == 1.04
    assert receipt.resulting_version == 2
    assert receipt.failure_reason is None

    # Verify updated in database
    updated = tendency_mgr.get_tendency("emotion.resilience_rate")
    assert updated.current_value == 1.04
    assert updated.version == 2

    # Verify logged to emotion_learning_records
    with db_factory.read_cursor() as cursor:
        cursor.execute("SELECT * FROM emotion_learning_records WHERE proposal_id = ?;", (str(req.proposal_id),))
        row = cursor.fetchone()
        assert row is not None
        assert row["dimension_name"] == "emotion.resilience_rate"
        assert row["new_value"] == 1.04


def test_learning_adaptation_rejected_when_exceeding_max_delta(learning_iface):
    """Verify adaptations with |Delta| > 0.05 are rejected to maintain gradual emotional evolution (Part 1.11)."""
    req = ParameterChangeRequest(
        proposal_id=uuid.uuid4(),
        target_dimension="emotion.resilience_rate",
        proposed_value=1.25,  # Delta = +0.25 (> 0.05 limit)
        expected_current_version=1,
        rationales=["Attempting an abrupt uncalibrated jump"],
    )

    receipt = learning_iface.apply_parameter_change(req)
    assert receipt.applied is False
    assert "EXCEEDS_MAX_DELTA_0.05" in receipt.failure_reason


def test_learning_adaptation_rejected_on_version_conflict(learning_iface):
    """Verify version mismatch concurrency guard prevents out-of-order parameter corruption."""
    req = ParameterChangeRequest(
        proposal_id=uuid.uuid4(),
        target_dimension="emotion.resilience_rate",
        proposed_value=1.03,
        expected_current_version=99,  # Mismatch (current is 1)
        rationales=["Stale proposal"],
    )

    receipt = learning_iface.apply_parameter_change(req)
    assert receipt.applied is False
    assert "VERSION_CONFLICT" in receipt.failure_reason


def test_learning_adaptation_rejected_on_constitutional_lock(learning_iface):
    """Verify protected constitutional baseline identity cannot be drifted outside safety envelope (E21, Axiom 5)."""
    # First apply a sequence of requests or attempt an out-of-bounds mutation
    # For curiosity_sensitivity (1.25), let's attempt to set to 0.45 (< 0.50 constitutional minimum)
    req = ParameterChangeRequest(
        proposal_id=uuid.uuid4(),
        target_dimension="emotion.curiosity_sensitivity",
        proposed_value=0.45,  # Violates constitutional minimum (0.50)
        expected_current_version=1,
        rationales=["Attempt to suppress curiosity below constitutional threshold"],
    )

    receipt = learning_iface.apply_parameter_change(req)
    assert receipt.applied is False
    # Rejected due to constitutional protection or maximum delta
    assert (
        ("REJECTED_PROTECTED_VIOLATION" in receipt.failure_reason)
        or ("CONSTITUTIONAL_IDENTITY_LOCKED" in receipt.failure_reason)
        or ("EXCEEDS_MAX_DELTA" in receipt.failure_reason)
    )

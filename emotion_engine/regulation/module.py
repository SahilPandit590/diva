"""
Emotion Regulation Module for Diva Emotion Engine v1.0.0.
Component 9 from Part 2 & Part 1.9.
Executes formal psychological regulation strategies (Cognitive Reappraisal, Attentional Deployment,
Pacing, Expressive Modulation) while strictly enforcing the Anti-Suppression Invariant (Axiom 3):
Regulates acute intensity without ever erasing or rewriting historical event records.
"""

from datetime import datetime, timezone
from typing import Optional
import uuid

from emotion_engine.database.connection import DatabaseConnectionFactory
from emotion_engine.lifecycle.manager import EmotionalLifecycleManager
from emotion_engine.regulation.strategies import REGULATION_STRATEGIES
from emotion_engine.types.enums import (
    EmotionState,
    LifecycleEntityType,
    RegulationStrategyType,
)
from emotion_engine.types.models import RegulationRecord


class EmotionRegulationModule:
    """Dispatches, executes, and audits internal emotional regulation strategies."""

    def __init__(
        self,
        factory: DatabaseConnectionFactory,
        lifecycle: EmotionalLifecycleManager,
    ):
        self.factory = factory
        self.lifecycle = lifecycle

    @staticmethod
    def select_strategy(category_name: str, current_intensity: float) -> RegulationStrategyType:
        """Heuristically selects optimal regulation strategy for a given emotion and intensity."""
        cat_upper = category_name.strip().upper()
        if cat_upper in ("ANGER", "FRUSTRATION", "RESENTMENT", "JEALOUSY"):
            return RegulationStrategyType.COGNITIVE_REAPPRAISAL
        elif cat_upper in ("FEAR", "ANXIETY"):
            return RegulationStrategyType.ATTENTIONAL_DEPLOYMENT
        elif cat_upper in ("DISTRESS", "SURPRISE"):
            return RegulationStrategyType.PACING_HEURISTIC
        else:
            return RegulationStrategyType.COGNITIVE_REAPPRAISAL

    def regulate_emotion(
        self,
        emotion_id: uuid.UUID,
        strategy_type: Optional[RegulationStrategyType] = None,
        current_time: Optional[datetime] = None,
    ) -> RegulationRecord:
        """
        Executes internal emotional regulation on an active emotion instance (E16, E18).
        - Computes damped intensity.
        - Transitions emotion through REGULATING -> SUSTAINED_DECAY.
        - Persists audit trail into emotion_regulation_records and emotion_lifecycle_events.
        - Anti-Suppression Invariant: Historical trigger and creation remain completely intact.
        """
        now = current_time or datetime.now(timezone.utc)
        now_iso = now.isoformat()

        with self.factory.read_cursor() as cursor:
            cursor.execute(
                """
                SELECT emotion_id, category_name, current_intensity, state
                FROM emotion_records
                WHERE emotion_id = ?;
                """,
                (str(emotion_id),),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Emotion {emotion_id} does not exist.")

        curr_intensity = float(row["current_intensity"])
        category = row["category_name"]
        curr_state = EmotionState(row["state"])

        strat = strategy_type or self.select_strategy(category, curr_intensity)
        strat_def = REGULATION_STRATEGIES[strat]

        # Calculate regulated intensity
        damped_intensity = max(0.05, round(curr_intensity * (1.0 - strat_def.damping_factor), 4))
        regulation_id = uuid.uuid4()

        # Execute regulation state transitions
        # 1. Transition to REGULATING
        if curr_state != EmotionState.REGULATING:
            self.lifecycle.transition_emotion_state(
                emotion_id=emotion_id,
                new_state=EmotionState.REGULATING,
                triggering_factor=f"Dispatched {strat_def.name} strategy",
                intensity_delta=round(damped_intensity - curr_intensity, 4),
            )

        # 2. Update intensity in database
        with self.factory.write_transaction() as cursor:
            cursor.execute(
                """
                UPDATE emotion_records
                SET current_intensity = ?, last_renewed_at = ?
                WHERE emotion_id = ?;
                """,
                (damped_intensity, now_iso, str(emotion_id)),
            )

            cursor.execute(
                """
                UPDATE emotion_intensities
                SET calibrated_intensity = ?, calculated_at = ?
                WHERE emotion_id = ?;
                """,
                (damped_intensity, now_iso, str(emotion_id)),
            )

            # Record regulation audit log
            cursor.execute(
                """
                INSERT INTO emotion_regulation_records (
                    regulation_id, emotion_id, strategy_used,
                    intensity_before, intensity_after, was_successful, executed_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?);
                """,
                (
                    str(regulation_id),
                    str(emotion_id),
                    strat.value,
                    curr_intensity,
                    damped_intensity,
                    now_iso,
                ),
            )

            self.lifecycle.log_lifecycle_event_in_tx(
                cursor=cursor,
                entity_type=LifecycleEntityType.REGULATION,
                entity_id=str(regulation_id),
                previous_state=f"Intensity: {curr_intensity:.2f}",
                new_state=f"Intensity: {damped_intensity:.2f}",
                transition_reason=f"Regulated via {strat_def.name} (damping: -{strat_def.damping_factor*100:.0f}%)",
            )

        # 3. Transition to SUSTAINED_DECAY
        self.lifecycle.transition_emotion_state(
            emotion_id=emotion_id,
            new_state=EmotionState.SUSTAINED_DECAY,
            triggering_factor=f"Regulation stabilized via {strat_def.name}",
            intensity_delta=0.0,
        )

        return RegulationRecord(
            regulation_id=regulation_id,
            emotion_id=emotion_id,
            strategy_used=strat,
            intensity_before=curr_intensity,
            intensity_after=damped_intensity,
            was_successful=True,
            executed_at=now,
        )

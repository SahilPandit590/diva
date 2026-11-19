"""
Emotion Transition & Decay Manager for Diva Emotion Engine v1.0.0.
Component 6 from Part 2 & Part 1.5.
Executes non-linear exponential decay calculations, renewal mechanics,
surge-to-decay transitions, and extinction pruning at threshold I < 0.05.
"""

from datetime import datetime, timezone
import math
from typing import Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field

from emotion_engine.database.connection import DatabaseConnectionFactory
from emotion_engine.lifecycle.manager import EmotionalLifecycleManager
from emotion_engine.types.enums import EmotionState, LifecycleEntityType
from emotion_engine.types.models import EmotionRecord
from emotion_engine.types.registry import EMOTION_REGISTRY

# Part 1.5 Specification Thresholds
FADING_EXTINCTION_THRESHOLD = 0.05
ACTIVE_SURGE_WINDOW_SECONDS = 10.0


class DecayRunResult(BaseModel):
    """Result summary of an active emotion decay execution pass."""
    model_config = ConfigDict(frozen=True)

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    active_before_count: int
    decayed_count: int
    extinct_count: int
    active_after_count: int
    extinct_emotion_ids: List[uuid.UUID] = Field(default_factory=list)


class EmotionTransitionManager:
    """Governs temporal dynamics, exponential decay curves, and extinction transitions."""

    def __init__(
        self,
        factory: DatabaseConnectionFactory,
        lifecycle: EmotionalLifecycleManager,
    ):
        self.factory = factory
        self.lifecycle = lifecycle
        self._half_life_cache: Dict[str, float] = {}

    def get_half_life(self, category_name: str) -> float:
        """Looks up emotion-specific decay half-life in seconds."""
        normalized = category_name.strip().upper()
        if normalized in self._half_life_cache:
            return self._half_life_cache[normalized]

        with self.factory.read_cursor() as cursor:
            cursor.execute(
                "SELECT half_life_seconds FROM emotion_decay_profiles WHERE UPPER(emotion_category) = ?;",
                (normalized,),
            )
            row = cursor.fetchone()
            if row:
                half_life = float(row["half_life_seconds"])
                self._half_life_cache[normalized] = half_life
                return half_life

        # Fallback to registry
        emotion_def = EMOTION_REGISTRY.get(category_name)
        if emotion_def:
            half_life = emotion_def.half_life_seconds
            self._half_life_cache[normalized] = half_life
            return half_life

        # Default standard half-life (10 minutes)
        return 600.0

    @staticmethod
    def compute_decayed_intensity(
        initial_intensity: float,
        elapsed_seconds: float,
        half_life_seconds: float,
    ) -> float:
        """
        Calculates exponential decay:
        I(t) = I_0 * 2^(-elapsed_seconds / half_life_seconds)
        """
        if elapsed_seconds <= 0.0:
            return initial_intensity

        half_life = max(1.0, half_life_seconds)
        decay_factor = math.pow(2.0, -elapsed_seconds / half_life)
        return max(0.0, min(1.0, round(initial_intensity * decay_factor, 4)))

    @staticmethod
    def apply_renewal_boost(
        current_intensity: float,
        boost_delta: float,
    ) -> float:
        """
        Applies renewal boost when a matching stimulus arrives:
        I_new = min(1.0, I_current + delta_I)
        """
        return max(0.0, min(1.0, round(current_intensity + boost_delta, 4)))

    def renew_emotion(
        self,
        emotion_id: uuid.UUID,
        boost_delta: float,
        current_time: Optional[datetime] = None,
    ) -> EmotionRecord:
        """
        Renews an existing active emotion upon arrival of a matching trigger stimulus (E14).
        Increases intensity, resets last_renewed_at, and boosts state to ACTIVE_SURGE.
        """
        now = current_time or datetime.now(timezone.utc)
        now_iso = now.isoformat()

        with self.factory.write_transaction() as cursor:
            cursor.execute(
                "SELECT current_intensity, state FROM emotion_records WHERE emotion_id = ?;",
                (str(emotion_id),),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Emotion {emotion_id} does not exist.")

            curr_intensity = row["current_intensity"]
            new_intensity = self.apply_renewal_boost(curr_intensity, boost_delta)

            # Update intensity and reset last_renewed_at
            cursor.execute(
                """
                UPDATE emotion_records
                SET current_intensity = ?,
                    state = 'ACTIVE_SURGE',
                    last_renewed_at = ?
                WHERE emotion_id = ?;
                """,
                (new_intensity, now_iso, str(emotion_id)),
            )

            cursor.execute(
                """
                UPDATE emotion_intensities
                SET calibrated_intensity = ?, calculated_at = ?
                WHERE emotion_id = ?;
                """,
                (new_intensity, now_iso, str(emotion_id)),
            )

            # Record transition
            cursor.execute(
                """
                INSERT INTO emotion_transitions (
                    transition_id, emotion_id, previous_state, new_state,
                    triggering_factor, intensity_delta, transitioned_at
                ) VALUES (?, ?, ?, 'ACTIVE_SURGE', 'RENEWAL_BOOST', ?, ?);
                """,
                (
                    str(uuid.uuid4()),
                    str(emotion_id),
                    row["state"],
                    boost_delta,
                    now_iso,
                ),
            )

            self.lifecycle.log_lifecycle_event_in_tx(
                cursor=cursor,
                entity_type=LifecycleEntityType.EMOTION,
                entity_id=str(emotion_id),
                previous_state=row["state"],
                new_state="ACTIVE_SURGE",
                transition_reason=f"Renewed with boost +{boost_delta:.2f} (new I={new_intensity:.2f})",
            )

        with self.factory.read_cursor() as cursor:
            cursor.execute("SELECT * FROM emotion_records WHERE emotion_id = ?;", (str(emotion_id),))
            return self.lifecycle._row_to_emotion_record(cursor.fetchone())

    def decay_active_emotions(
        self,
        current_time: Optional[datetime] = None,
    ) -> DecayRunResult:
        """
        Executes a periodic temporal decay tick across all active non-extinct emotions.
        - Attenuates intensity according to exponential curve.
        - Moves from ACTIVE_SURGE to SUSTAINED_DECAY once surge window (10s) expires.
        - Transitions to EXTINCTION if intensity drops below 0.05 (E15).
        """
        now = current_time or datetime.now(timezone.utc)
        now_iso = now.isoformat()

        # 1. Fetch active emotions
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                """
                SELECT emotion_id, category_name, current_intensity, state,
                       created_at, last_renewed_at
                FROM emotion_records
                WHERE state != 'EXTINCTION';
                """
            )
            active_rows = cursor.fetchall()

        active_before = len(active_rows)
        decayed_count = 0
        extinct_count = 0
        extinct_ids: List[uuid.UUID] = []

        for row in active_rows:
            e_id = uuid.UUID(row["emotion_id"])
            cat_name = row["category_name"]
            initial_intensity = row["current_intensity"]
            curr_state = EmotionState(row["state"])
            last_renewed = datetime.fromisoformat(row["last_renewed_at"])

            elapsed_sec = max(0.0, (now - last_renewed).total_seconds())
            half_life = self.get_half_life(cat_name)

            new_intensity = self.compute_decayed_intensity(
                initial_intensity=initial_intensity,
                elapsed_seconds=elapsed_sec,
                half_life_seconds=half_life,
            )

            # Check for extinction
            if new_intensity < FADING_EXTINCTION_THRESHOLD:
                self.lifecycle.transition_emotion_state(
                    emotion_id=e_id,
                    new_state=EmotionState.EXTINCTION,
                    triggering_factor=f"Fading threshold crossed (<{FADING_EXTINCTION_THRESHOLD:.2f}) via natural decay",
                    intensity_delta=new_intensity - initial_intensity,
                )
                extinct_count += 1
                extinct_ids.append(e_id)
            else:
                # Update decayed intensity
                new_state = curr_state
                # Check if surge window expired
                if curr_state == EmotionState.ACTIVE_SURGE and elapsed_sec >= ACTIVE_SURGE_WINDOW_SECONDS:
                    new_state = EmotionState.SUSTAINED_DECAY

                with self.factory.write_transaction() as cursor:
                    cursor.execute(
                        """
                        UPDATE emotion_records
                        SET current_intensity = ?, state = ?
                        WHERE emotion_id = ?;
                        """,
                        (new_intensity, new_state.value, str(e_id)),
                    )
                    cursor.execute(
                        """
                        UPDATE emotion_intensities
                        SET calibrated_intensity = ?, calculated_at = ?
                        WHERE emotion_id = ?;
                        """,
                        (new_intensity, now_iso, str(e_id)),
                    )
                    if new_state != curr_state:
                        # Log transition from SURGE to SUSTAINED_DECAY
                        cursor.execute(
                            """
                            INSERT INTO emotion_transitions (
                                transition_id, emotion_id, previous_state, new_state,
                                triggering_factor, intensity_delta, transitioned_at
                            ) VALUES (?, ?, ?, ?, 'Surge window elapsed', 0.0, ?);
                            """,
                            (str(uuid.uuid4()), str(e_id), curr_state.value, new_state.value, now_iso),
                        )
                        self.lifecycle.log_lifecycle_event_in_tx(
                            cursor=cursor,
                            entity_type=LifecycleEntityType.EMOTION,
                            entity_id=str(e_id),
                            previous_state=curr_state.value,
                            new_state=new_state.value,
                            transition_reason="Surge window elapsed into sustained decay",
                        )
                decayed_count += 1

        active_after = active_before - extinct_count

        return DecayRunResult(
            timestamp=now,
            active_before_count=active_before,
            decayed_count=decayed_count,
            extinct_count=extinct_count,
            active_after_count=active_after,
            extinct_emotion_ids=extinct_ids,
        )

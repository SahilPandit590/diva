"""
3D Circumplex Mood Manager for Diva Emotion Engine v1.0.0.
Component 7 from Part 2 & Part 1.6.
Maintains persistent background affective climate in <V, A, D> space.
Implements heavily damped moving-average integration (alpha = 0.001)
with single-event delta clamping (<= 0.05).
"""

from datetime import datetime, timezone
import json
from typing import List, Optional, Tuple
import uuid

from emotion_engine.database.connection import DatabaseConnectionFactory
from emotion_engine.lifecycle.manager import EmotionalLifecycleManager
from emotion_engine.types.enums import LifecycleEntityType
from emotion_engine.types.models import EmotionRecord, MoodHistory, MoodRecord
from emotion_engine.types.registry import EMOTION_REGISTRY

# Part 1.6 & Phase 4 Constants
MOOD_INTEGRATION_RATE_ALPHA = 0.001
MAX_SINGLE_EVENT_DELTA = 0.05


class MoodManager:
    """Manages continuous background circumplex mood and historical trajectories."""

    def __init__(
        self,
        factory: DatabaseConnectionFactory,
        lifecycle: EmotionalLifecycleManager,
        alpha: float = MOOD_INTEGRATION_RATE_ALPHA,
    ):
        self.factory = factory
        self.lifecycle = lifecycle
        self.alpha = alpha

    def get_current_mood(self) -> MoodRecord:
        """Retrieves active circumplex mood record from database."""
        return self.lifecycle.recover_current_mood()

    @staticmethod
    def derive_mood_label(v: float, a: float, d: float) -> str:
        """Maps 3D continuous PAD vector to psychological qualitative descriptor."""
        if abs(v) <= 0.15 and abs(a) <= 0.15 and abs(d) <= 0.15:
            return "Equanimous Neutral"

        is_pos_v = (v >= 0.0)
        is_pos_a = (a >= 0.0)
        is_pos_d = (d >= 0.0)

        if is_pos_v and is_pos_a and is_pos_d:
            return "Buoyant Optimism"
        elif is_pos_v and is_pos_a and not is_pos_d:
            return "Playful Excitement"
        elif is_pos_v and not is_pos_a and is_pos_d:
            return "Serene Tranquility"
        elif is_pos_v and not is_pos_a and not is_pos_d:
            return "Gentle Contentment"
        elif not is_pos_v and is_pos_a and is_pos_d:
            return "Agitated Frustration"
        elif not is_pos_v and is_pos_a and not is_pos_d:
            return "Apprehensive Tension"
        elif not is_pos_v and not is_pos_a and is_pos_d:
            return "Cold Detachment"
        else:
            return "Reflective Melancholy"

    def update_mood(
        self,
        active_emotions: List[EmotionRecord],
        elapsed_seconds: float = 1.0,
        current_time: Optional[datetime] = None,
    ) -> MoodRecord:
        """
        Integrates active emotional vector pull into persistent mood using damped moving average.
        Enforces single-event delta clamping (<= 0.05) per update pass (Phase 4 Gate).
        """
        now = current_time or datetime.now(timezone.utc)
        now_iso = now.isoformat()
        current_mood = self.get_current_mood()

        if not active_emotions:
            # When idle with no active emotions, mood slowly relaxes toward neutral
            target_v, target_a, target_d = 0.0, 0.0, 0.0
        else:
            # Calculate intensity-weighted average PAD pull of active emotions
            total_intensity = sum(e.current_intensity for e in active_emotions)
            if total_intensity <= 1e-6:
                target_v, target_a, target_d = current_mood.valence, current_mood.arousal, current_mood.dominance
            else:
                sum_v = 0.0
                sum_a = 0.0
                sum_d = 0.0
                for e in active_emotions:
                    edef = EMOTION_REGISTRY.get(e.category_name)
                    if edef:
                        sum_v += edef.valence * e.current_intensity
                        sum_a += edef.arousal * e.current_intensity
                        sum_d += edef.dominance * e.current_intensity
                target_v = sum_v / total_intensity
                target_a = sum_a / total_intensity
                target_d = sum_d / total_intensity

        # Compute raw delta
        effective_alpha = min(1.0, max(0.0001, self.alpha * elapsed_seconds))
        raw_delta_v = effective_alpha * (target_v - current_mood.valence)
        raw_delta_a = effective_alpha * (target_a - current_mood.arousal)
        raw_delta_d = effective_alpha * (target_d - current_mood.dominance)

        # Enforce single-event delta clamp (<= MAX_SINGLE_EVENT_DELTA)
        clamped_delta_v = max(-MAX_SINGLE_EVENT_DELTA, min(MAX_SINGLE_EVENT_DELTA, raw_delta_v))
        clamped_delta_a = max(-MAX_SINGLE_EVENT_DELTA, min(MAX_SINGLE_EVENT_DELTA, raw_delta_a))
        clamped_delta_d = max(-MAX_SINGLE_EVENT_DELTA, min(MAX_SINGLE_EVENT_DELTA, raw_delta_d))

        new_v = max(-1.0, min(1.0, round(current_mood.valence + clamped_delta_v, 4)))
        new_a = max(-1.0, min(1.0, round(current_mood.arousal + clamped_delta_a, 4)))
        new_d = max(-1.0, min(1.0, round(current_mood.dominance + clamped_delta_d, 4)))

        new_label = self.derive_mood_label(new_v, new_a, new_d)

        # Update database
        with self.factory.write_transaction() as cursor:
            cursor.execute(
                """
                UPDATE emotion_mood_record
                SET valence = ?, arousal = ?, dominance = ?,
                    label_descriptor = ?, updated_at = ?
                WHERE mood_id = ?;
                """,
                (new_v, new_a, new_d, new_label, now_iso, str(current_mood.mood_id)),
            )

            self.lifecycle.log_lifecycle_event_in_tx(
                cursor=cursor,
                entity_type=LifecycleEntityType.MOOD,
                entity_id=str(current_mood.mood_id),
                previous_state=f"PAD({current_mood.valence:.2f}, {current_mood.arousal:.2f}, {current_mood.dominance:.2f})",
                new_state=f"PAD({new_v:.2f}, {new_a:.2f}, {new_d:.2f}) [{new_label}]",
                transition_reason=f"Mood integration pass (delta_v={clamped_delta_v:+.4f})",
            )

        return MoodRecord(
            mood_id=current_mood.mood_id,
            valence=new_v,
            arousal=new_a,
            dominance=new_d,
            label_descriptor=new_label,
            stability_metric=current_mood.stability_metric,
            updated_at=now,
        )

    def record_mood_history(
        self,
        driving_emotion_ids: Tuple[uuid.UUID, ...],
        current_time: Optional[datetime] = None,
    ) -> MoodHistory:
        """Records current mood snapshot into emotion_mood_history table."""
        now = current_time or datetime.now(timezone.utc)
        now_iso = now.isoformat()
        curr_mood = self.get_current_mood()
        history_id = uuid.uuid4()
        driving_json = json.dumps([str(eid) for eid in driving_emotion_ids])

        with self.factory.write_transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO emotion_mood_history (
                    history_id, valence_snapshot, arousal_snapshot,
                    dominance_snapshot, driving_emotion_ids_json, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    str(history_id),
                    curr_mood.valence,
                    curr_mood.arousal,
                    curr_mood.dominance,
                    driving_json,
                    now_iso,
                ),
            )

        return MoodHistory(
            history_id=history_id,
            valence_snapshot=curr_mood.valence,
            arousal_snapshot=curr_mood.arousal,
            dominance_snapshot=curr_mood.dominance,
            driving_emotion_ids=driving_emotion_ids,
            recorded_at=now,
        )

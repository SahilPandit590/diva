"""
Emotional Tendency Manager for Diva Emotion Engine v1.0.0.
Component 10 from Part 2 & Part 1.10.
Maintains persistent baseline sensitivity multipliers, resilience recovery rates,
and distinguishes persistent personality-aligned tendencies from transient emotional states (E19).
"""

from datetime import datetime, timezone
from typing import Dict, Optional
import uuid

from emotion_engine.database.connection import DatabaseConnectionFactory
from emotion_engine.lifecycle.manager import EmotionalLifecycleManager
from emotion_engine.types.enums import LifecycleEntityType
from emotion_engine.types.models import EmotionalTendency


# Mapping of emotion categories to persistent tendency dimensions
CATEGORY_TO_TENDENCY_MAP: Dict[str, str] = {
    "CURIOSITY": "emotion.curiosity_sensitivity",
    "INTEREST": "emotion.curiosity_sensitivity",
    "ANGER": "emotion.anger_sensitivity",
    "FRUSTRATION": "emotion.anger_sensitivity",
    "RESENTMENT": "emotion.anger_sensitivity",
    "FEAR": "emotion.fear_sensitivity",
    "ANXIETY": "emotion.fear_sensitivity",
    "AFFECTION": "emotion.empathy_sensitivity",
    "COMPASSION": "emotion.empathy_sensitivity",
}


class EmotionalTendencyManager:
    """Manages Diva's unique persistent emotional baseline sensitivities and resilience."""

    def __init__(
        self,
        factory: DatabaseConnectionFactory,
        lifecycle: EmotionalLifecycleManager,
    ):
        self.factory = factory
        self.lifecycle = lifecycle

    def get_tendency(self, dimension_name: str) -> Optional[EmotionalTendency]:
        """Retrieves a specific emotional tendency dimension."""
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                """
                SELECT tendency_id, dimension_name, current_value, version,
                       is_constitutional_baseline, updated_at
                FROM emotion_tendencies
                WHERE dimension_name = ?;
                """,
                (dimension_name,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return EmotionalTendency(
                tendency_id=uuid.UUID(row["tendency_id"]),
                dimension_name=row["dimension_name"],
                current_value=float(row["current_value"]),
                version=int(row["version"]),
                is_constitutional_baseline=bool(row["is_constitutional_baseline"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )

    def get_all_tendencies(self) -> Dict[str, EmotionalTendency]:
        """Retrieves all registered emotional tendencies."""
        return self.lifecycle.recover_tendencies()

    def get_multiplier_for_category(self, category_name: str) -> float:
        """
        Looks up specific sensitivity multiplier for an emotion category.
        Falls back to emotion.reactivity_baseline if category is unmapped.
        """
        cat_upper = category_name.strip().upper()
        dim_name = CATEGORY_TO_TENDENCY_MAP.get(cat_upper, "emotion.reactivity_baseline")
        tendency = self.get_tendency(dim_name)
        if tendency:
            return tendency.current_value
        return 1.0

    def get_resilience_rate(self) -> float:
        """Returns resilience rate multiplier influencing recovery speed."""
        tendency = self.get_tendency("emotion.resilience_rate")
        return tendency.current_value if tendency else 1.0

    def update_tendency(
        self,
        dimension_name: str,
        new_value: float,
        expected_version: int,
        reason: str = "Owner parameter update",
        current_time: Optional[datetime] = None,
    ) -> EmotionalTendency:
        """Updates tendency value with optimistic concurrency version check."""
        now = current_time or datetime.now(timezone.utc)
        now_iso = now.isoformat()

        with self.factory.write_transaction() as cursor:
            cursor.execute(
                """
                SELECT tendency_id, current_value, version, is_constitutional_baseline
                FROM emotion_tendencies
                WHERE dimension_name = ?;
                """,
                (dimension_name,),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Tendency dimension {dimension_name} not found.")

            curr_ver = int(row["version"])
            if curr_ver != expected_version:
                raise ValueError(
                    f"Concurrency conflict on {dimension_name}: expected version {expected_version}, found {curr_ver}."
                )

            new_ver = curr_ver + 1
            tendency_id = uuid.UUID(row["tendency_id"])
            is_const = bool(row["is_constitutional_baseline"])

            cursor.execute(
                """
                UPDATE emotion_tendencies
                SET current_value = ?, version = ?, updated_at = ?
                WHERE dimension_name = ?;
                """,
                (new_value, new_ver, now_iso, dimension_name),
            )

            self.lifecycle.log_lifecycle_event_in_tx(
                cursor=cursor,
                entity_type=LifecycleEntityType.TENDENCY,
                entity_id=str(tendency_id),
                previous_state=f"{row['current_value']:.2f} (v{curr_ver})",
                new_state=f"{new_value:.2f} (v{new_ver})",
                transition_reason=reason,
            )

        return EmotionalTendency(
            tendency_id=tendency_id,
            dimension_name=dimension_name,
            current_value=new_value,
            version=new_ver,
            is_constitutional_baseline=is_const,
            updated_at=now,
        )

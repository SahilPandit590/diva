"""
Emotional Lifecycle Manager for Diva Emotion Engine v1.0.0.
Component 12 from Part 2 & Part 4.
Enforces closed, deterministic finite state machines, active pool constraints (max 10),
transactional persistence, and append-only lifecycle event logging.
"""

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from emotion_engine.database.connection import DatabaseConnectionFactory
from emotion_engine.types.enums import (
    EmotionState,
    EmotionType,
    LifecycleEntityType,
    ResolutionType,
    TriggerSource,
)
from emotion_engine.types.models import (
    EmotionRecord,
    EmotionalTendency,
    MoodRecord,
)


class InvalidEmotionStateTransitionError(ValueError):
    """Raised when an illegal lifecycle state transition is attempted."""
    pass


# Deterministic FSM defining permissible state transitions
VALID_STATE_TRANSITIONS: Dict[EmotionState, Set[EmotionState]] = {
    EmotionState.TRIGGERED: {
        EmotionState.ACTIVE_SURGE,
        EmotionState.REGULATING,
        EmotionState.EXTINCTION,
    },
    EmotionState.ACTIVE_SURGE: {
        EmotionState.SUSTAINED_DECAY,
        EmotionState.REGULATING,
        EmotionState.EXTINCTION,
    },
    EmotionState.SUSTAINED_DECAY: {
        EmotionState.ACTIVE_SURGE,  # Renewal boost on matching stimulus
        EmotionState.REGULATING,
        EmotionState.EXTINCTION,
    },
    EmotionState.REGULATING: {
        EmotionState.SUSTAINED_DECAY,
        EmotionState.ACTIVE_SURGE,
        EmotionState.EXTINCTION,
    },
    EmotionState.EXTINCTION: set(),  # Terminal state
}

MAX_ACTIVE_EMOTION_POOL_SIZE = 10


class EmotionalLifecycleManager:
    """Authoritative transaction and lifecycle governor for the Emotion Engine."""

    def __init__(self, factory: DatabaseConnectionFactory):
        self.factory = factory

    def log_lifecycle_event_in_tx(
        self,
        cursor: Any,
        entity_type: LifecycleEntityType,
        entity_id: str,
        previous_state: Optional[str],
        new_state: str,
        transition_reason: str,
    ) -> str:
        """Appends an immutable audit event to emotion_lifecycle_events."""
        event_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            """
            INSERT INTO emotion_lifecycle_events (
                event_id, entity_type, entity_id, previous_state,
                new_state, transition_reason, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                event_id,
                entity_type.value,
                str(entity_id),
                previous_state,
                new_state,
                transition_reason,
                now_iso,
            ),
        )
        return event_id

    def create_emotion(
        self,
        category_name: str,
        emotion_type: EmotionType,
        initial_intensity: float,
        source_engine: TriggerSource,
        source_event_id: str,
        trigger_type: str,
        assessed_significance: float,
        perceived_valence: float,
        trigger_contribution: float,
        mood_contribution: float,
        personality_multiplier: float,
        environmental_setting: str = "INTERNAL",
        social_interlocutor_id: Optional[str] = None,
        active_task_id: Optional[str] = None,
        uncertainty_score: float = 0.0,
        context_metadata: Optional[Dict[str, Any]] = None,
        derivation_chain: Optional[Tuple[str, ...]] = None,
    ) -> EmotionRecord:
        """
        Creates and persists a new emotion instance within an atomic transaction.
        Enforces active pool bounds (max 10) before creating.
        """
        emotion_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        with self.factory.write_transaction() as cursor:
            # 1. Enforce active pool bounds (max 10 concurrent active emotions)
            self._enforce_active_pool_bounds_in_tx(cursor)

            # 2. Insert into emotion_records in TRIGGERED state
            cursor.execute(
                """
                INSERT INTO emotion_records (
                    emotion_id, category_name, emotion_type,
                    current_intensity, state, created_at, last_renewed_at
                ) VALUES (?, ?, ?, ?, 'TRIGGERED', ?, ?);
                """,
                (
                    str(emotion_id),
                    category_name,
                    emotion_type.value,
                    initial_intensity,
                    now_iso,
                    now_iso,
                ),
            )

            # 3. Insert into emotion_intensities
            cursor.execute(
                """
                INSERT INTO emotion_intensities (
                    intensity_id, emotion_id, raw_intensity, calibrated_intensity,
                    trigger_contribution, mood_contribution, personality_multiplier, calculated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    str(uuid.uuid4()),
                    str(emotion_id),
                    initial_intensity,
                    initial_intensity,
                    trigger_contribution,
                    mood_contribution,
                    personality_multiplier,
                    now_iso,
                ),
            )

            # 4. Insert into emotion_triggers
            cursor.execute(
                """
                INSERT INTO emotion_triggers (
                    trigger_id, emotion_id, source_engine, source_event_id,
                    trigger_type, assessed_significance, perceived_valence, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    str(uuid.uuid4()),
                    str(emotion_id),
                    source_engine.value,
                    source_event_id,
                    trigger_type,
                    assessed_significance,
                    perceived_valence,
                    now_iso,
                ),
            )

            # 5. Insert into emotion_contexts
            cursor.execute(
                """
                INSERT INTO emotion_contexts (
                    context_id, emotion_id, social_interlocutor_id, environmental_setting,
                    active_task_id, uncertainty_score, context_metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    str(uuid.uuid4()),
                    str(emotion_id),
                    social_interlocutor_id,
                    environmental_setting,
                    active_task_id,
                    uncertainty_score,
                    json.dumps(context_metadata or {}),
                ),
            )

            # 6. Insert into emotion_provenance
            chain_tuple = derivation_chain or (f"{source_engine.value}_INGRESS", "TRIGGER_ANALYZER", "GENERATION_MODULE")
            cursor.execute(
                """
                INSERT INTO emotion_provenance (
                    provenance_id, emotion_id, source_engine, source_event_id,
                    derivation_chain_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    str(uuid.uuid4()),
                    str(emotion_id),
                    source_engine.value,
                    source_event_id,
                    json.dumps(list(chain_tuple)),
                    now_iso,
                ),
            )

            # 7. Log lifecycle audit event
            self.log_lifecycle_event_in_tx(
                cursor=cursor,
                entity_type=LifecycleEntityType.EMOTION,
                entity_id=str(emotion_id),
                previous_state=None,
                new_state=EmotionState.TRIGGERED.value,
                transition_reason=f"Generated via {trigger_type} trigger from {source_engine.value}",
            )

        return EmotionRecord(
            emotion_id=emotion_id,
            category_name=category_name,
            emotion_type=emotion_type,
            current_intensity=initial_intensity,
            state=EmotionState.TRIGGERED,
            created_at=now,
            last_renewed_at=now,
        )

    def transition_emotion_state(
        self,
        emotion_id: uuid.UUID,
        new_state: EmotionState,
        triggering_factor: str,
        intensity_delta: float = 0.0,
    ) -> EmotionRecord:
        """
        Validates and applies an emotion state transition according to the FSM.
        Records entry in emotion_transitions and emotion_lifecycle_events.
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        with self.factory.write_transaction() as cursor:
            cursor.execute(
                """
                SELECT emotion_id, category_name, emotion_type, current_intensity,
                       state, created_at, last_renewed_at
                FROM emotion_records
                WHERE emotion_id = ?;
                """,
                (str(emotion_id),),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Emotion {emotion_id} does not exist.")

            curr_state = EmotionState(row["state"])
            if curr_state == new_state:
                # No-op transition
                return self._row_to_emotion_record(row)

            # Verify permissible transition
            allowed = VALID_STATE_TRANSITIONS.get(curr_state, set())
            if new_state not in allowed:
                raise InvalidEmotionStateTransitionError(
                    f"Illegal transition: Emotion {emotion_id} cannot transition from {curr_state.value} to {new_state.value}."
                )

            # Update emotion_records state
            cursor.execute(
                """
                UPDATE emotion_records
                SET state = ?, last_renewed_at = ?
                WHERE emotion_id = ?;
                """,
                (new_state.value, now_iso, str(emotion_id)),
            )

            # Record in emotion_transitions
            cursor.execute(
                """
                INSERT INTO emotion_transitions (
                    transition_id, emotion_id, previous_state, new_state,
                    triggering_factor, intensity_delta, transitioned_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    str(uuid.uuid4()),
                    str(emotion_id),
                    curr_state.value,
                    new_state.value,
                    triggering_factor,
                    intensity_delta,
                    now_iso,
                ),
            )

            # Log in emotion_lifecycle_events
            self.log_lifecycle_event_in_tx(
                cursor=cursor,
                entity_type=LifecycleEntityType.EMOTION,
                entity_id=str(emotion_id),
                previous_state=curr_state.value,
                new_state=new_state.value,
                transition_reason=triggering_factor,
            )

            # If transitioning to EXTINCTION, archive to historical events
            if new_state == EmotionState.EXTINCTION:
                self._archive_extinct_emotion_in_tx(
                    cursor=cursor,
                    emotion_id=emotion_id,
                    category=row["category_name"],
                    created_at_iso=row["created_at"],
                    now_iso=now_iso,
                    resolution_type=ResolutionType.NATURAL_DECAY if "decay" in triggering_factor.lower() else ResolutionType.REGULATED,
                )

            cursor.execute("SELECT * FROM emotion_records WHERE emotion_id = ?;", (str(emotion_id),))
            updated_row = cursor.fetchone()
            return self._row_to_emotion_record(updated_row)

    def _enforce_active_pool_bounds_in_tx(self, cursor: Any) -> None:
        """
        Enforces maximum 10 active concurrent emotions (E30).
        If at capacity (>= 10), gracefully transitions the lowest intensity
        sustained emotion to EXTINCTION.
        """
        cursor.execute(
            """
            SELECT count(*) as cnt FROM emotion_records
            WHERE state != 'EXTINCTION';
            """
        )
        active_count = cursor.fetchone()["cnt"]

        if active_count >= MAX_ACTIVE_EMOTION_POOL_SIZE:
            # Find candidate for graceful retirement: lowest intensity in SUSTAINED_DECAY or oldest
            cursor.execute(
                """
                SELECT emotion_id, category_name, created_at, state
                FROM emotion_records
                WHERE state != 'EXTINCTION'
                ORDER BY (state = 'SUSTAINED_DECAY') DESC, current_intensity ASC, created_at ASC
                LIMIT 1;
                """
            )
            retire_row = cursor.fetchone()
            if retire_row:
                retire_id = uuid.UUID(retire_row["emotion_id"])
                now_iso = datetime.now(timezone.utc).isoformat()
                cursor.execute(
                    "UPDATE emotion_records SET state = 'EXTINCTION' WHERE emotion_id = ?;",
                    (str(retire_id),),
                )
                self.log_lifecycle_event_in_tx(
                    cursor=cursor,
                    entity_type=LifecycleEntityType.EMOTION,
                    entity_id=str(retire_id),
                    previous_state=retire_row["state"],
                    new_state="EXTINCTION",
                    transition_reason="Active pool capacity limit reached (max 10); retiring lowest intensity",
                )
                self._archive_extinct_emotion_in_tx(
                    cursor=cursor,
                    emotion_id=retire_id,
                    category=retire_row["category_name"],
                    created_at_iso=retire_row["created_at"],
                    now_iso=now_iso,
                    resolution_type=ResolutionType.OVERWRITTEN,
                )

    def _archive_extinct_emotion_in_tx(
        self,
        cursor: Any,
        emotion_id: uuid.UUID,
        category: str,
        created_at_iso: str,
        now_iso: str,
        resolution_type: ResolutionType = ResolutionType.NATURAL_DECAY,
    ) -> None:
        """Archives extinct emotion to permanent affective history."""
        # Calculate duration
        t_start = datetime.fromisoformat(created_at_iso)
        t_end = datetime.fromisoformat(now_iso)
        duration_sec = max(1, int((t_end - t_start).total_seconds()))

        # Query peak intensity from intensities table
        cursor.execute(
            "SELECT raw_intensity FROM emotion_intensities WHERE emotion_id = ?;",
            (str(emotion_id),),
        )
        row = cursor.fetchone()
        peak_intensity = row["raw_intensity"] if row else 0.5

        cursor.execute(
            """
            INSERT INTO emotion_historical_events (
                history_entry_id, emotion_id, category, peak_intensity,
                duration_seconds, resolution_type, closed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                str(uuid.uuid4()),
                str(emotion_id),
                category,
                peak_intensity,
                duration_sec,
                resolution_type.value,
                now_iso,
            ),
        )

    def recover_active_emotions(self) -> List[EmotionRecord]:
        """Recovers all active (non-extinct) emotions after process restart."""
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                """
                SELECT emotion_id, category_name, emotion_type, current_intensity,
                       state, created_at, last_renewed_at
                FROM emotion_records
                WHERE state != 'EXTINCTION'
                ORDER BY created_at ASC;
                """
            )
            rows = cursor.fetchall()
            return [self._row_to_emotion_record(r) for r in rows]

    def recover_current_mood(self) -> MoodRecord:
        """Recovers current circumplex mood from emotion_mood_record."""
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                """
                SELECT mood_id, valence, arousal, dominance, label_descriptor,
                       stability_metric, updated_at
                FROM emotion_mood_record
                ORDER BY updated_at DESC LIMIT 1;
                """
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("No mood record found in database.")
            return MoodRecord(
                mood_id=uuid.UUID(row["mood_id"]),
                valence=row["valence"],
                arousal=row["arousal"],
                dominance=row["dominance"],
                label_descriptor=row["label_descriptor"],
                stability_metric=row["stability_metric"],
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )

    def recover_tendencies(self) -> Dict[str, EmotionalTendency]:
        """Recovers all emotional tendencies and sensitivities."""
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                """
                SELECT tendency_id, dimension_name, current_value, version,
                       is_constitutional_baseline, updated_at
                FROM emotion_tendencies;
                """
            )
            rows = cursor.fetchall()
            return {
                r["dimension_name"]: EmotionalTendency(
                    tendency_id=uuid.UUID(r["tendency_id"]),
                    dimension_name=r["dimension_name"],
                    current_value=r["current_value"],
                    version=r["version"],
                    is_constitutional_baseline=bool(r["is_constitutional_baseline"]),
                    updated_at=datetime.fromisoformat(r["updated_at"]),
                )
                for r in rows
            }

    @staticmethod
    def _row_to_emotion_record(row: Any) -> EmotionRecord:
        return EmotionRecord(
            emotion_id=uuid.UUID(row["emotion_id"]),
            category_name=row["category_name"],
            emotion_type=EmotionType(row["emotion_type"]),
            current_intensity=row["current_intensity"],
            state=EmotionState(row["state"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            last_renewed_at=datetime.fromisoformat(row["last_renewed_at"]),
        )

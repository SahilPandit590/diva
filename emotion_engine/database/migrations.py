"""
Migration and Schema Initialization Runner for Diva Emotion Engine v1.0.0.
Creates all 16 relational tables, registers indexes, and seeds foundational
decay profiles, baseline tendencies, and initial circumplex mood.
"""

from datetime import datetime, timezone
import uuid

from emotion_engine.database.connection import DatabaseConnectionFactory
from emotion_engine.database.schema import SCHEMA_SQL
from emotion_engine.types.registry import EMOTION_REGISTRY


class MigrationRunner:
    """Manages database schema creation and baseline domain data seeding."""

    def __init__(self, factory: DatabaseConnectionFactory):
        self.factory = factory

    def apply_migrations(self) -> None:
        """Executes full schema initialization and idempotent data seeding."""
        # 1. Execute DDL for all 16 tables and indexes outside explicit transaction
        self.factory.execute_script(SCHEMA_SQL)

        now_iso = datetime.now(timezone.utc).isoformat()

        # 2. Seed Predefined Decay Profiles, Baseline Tendencies & Default Mood in a write transaction
        with self.factory.write_transaction() as cursor:
            # Seed Predefined Decay Profiles from EmotionRegistry (30 canonical emotions)
            for emotion_def in EMOTION_REGISTRY.list_all():
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO emotion_decay_profiles (
                        profile_id, emotion_category, half_life_seconds,
                        decay_curve_type, quiescent_baseline
                    ) VALUES (?, ?, ?, ?, ?);
                    """,
                    (
                        str(uuid.uuid4()),
                        emotion_def.name,
                        emotion_def.half_life_seconds,
                        emotion_def.decay_curve.value,
                        emotion_def.quiescent_baseline,
                    ),
                )

            # Seed Constitutional Baseline & Adaptable Developed Tendencies (Part 1 Section 10 & 11)
            baseline_tendencies = [
                ("emotion.curiosity_sensitivity", 1.25, 1),
                ("emotion.joy_sensitivity", 1.10, 1),
                ("emotion.resilience_rate", 1.00, 0),
                ("emotion.empathy_sensitivity", 1.15, 1),
                ("emotion.reactivity_baseline", 1.00, 1),
                ("emotion.anger_sensitivity", 0.70, 1),
                ("emotion.fear_sensitivity", 0.85, 1),
                ("emotion.regulation_efficiency", 1.10, 0),
                ("emotion.social_trust_baseline", 0.70, 0),
            ]

            for dim_name, val, is_const in baseline_tendencies:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO emotion_tendencies (
                        tendency_id, dimension_name, current_value,
                        version, is_constitutional_baseline, updated_at
                    ) VALUES (?, ?, ?, 1, ?, ?);
                    """,
                    (
                        str(uuid.uuid4()),
                        dim_name,
                        val,
                        is_const,
                        now_iso,
                    ),
                )

            # Seed Default Resting Circumplex Mood (Equanimous Neutral) if empty
            cursor.execute("SELECT count(*) as cnt FROM emotion_mood_record;")
            if cursor.fetchone()["cnt"] == 0:
                cursor.execute(
                    """
                    INSERT INTO emotion_mood_record (
                        mood_id, valence, arousal, dominance,
                        label_descriptor, stability_metric, updated_at
                    ) VALUES (?, 0.0, 0.0, 0.0, 'Equanimous Neutral', 0.8, ?);
                    """,
                    (str(uuid.uuid4()), now_iso),
                )

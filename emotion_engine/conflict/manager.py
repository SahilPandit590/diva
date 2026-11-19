"""
Emotional Conflict & Mixed Blend Manager for Diva Emotion Engine v1.0.0.
Component 8 from Part 2 & Part 1.8.
Identifies ambivalent pairs, calculates bimodal emotional tension metrics (Delta_tension),
recognizes emergent mixed emotion blends, and preserves structural coexistence
without artificial cancellation or neutral collapse.
"""

from datetime import datetime, timezone
import json
from typing import Dict, List, Optional, Set, Tuple
import uuid

from emotion_engine.database.connection import DatabaseConnectionFactory
from emotion_engine.lifecycle.manager import EmotionalLifecycleManager
from emotion_engine.types.enums import ConflictCategory
from emotion_engine.types.models import (
    EmotionRecord,
    EmotionalConflict,
    MixedEmotionState,
)
from emotion_engine.types.registry import EMOTION_REGISTRY

# Predefined canonical mixed blend patterns
CANONICAL_BLENDS: Dict[frozenset, str] = {
    frozenset({"HAPPINESS", "SADNESS"}): "Bittersweetness",
    frozenset({"AFFECTION", "SADNESS"}): "Nostalgic Longing",
    frozenset({"FEAR", "ANTICIPATION"}): "Anxious Trepidation",
    frozenset({"ANGER", "DISTRESS"}): "Frustrated Agitation",
    frozenset({"HAPPINESS", "ANTICIPATION"}): "Exuberant Eagerness",
    frozenset({"AFFECTION", "ANGER"}): "Conflicted Attachment",
    frozenset({"CURIOSITY", "FEAR"}): "Trepidatious Wonder",
    frozenset({"HAPPINESS", "AFFECTION"}): "Warm Tender Delight",
}


class EmotionalConflictManager:
    """Manages emotional ambivalence, conflicting pairs, and mixed affective blends."""

    def __init__(
        self,
        factory: DatabaseConnectionFactory,
        lifecycle: EmotionalLifecycleManager,
    ):
        self.factory = factory
        self.lifecycle = lifecycle

    def detect_conflicts(
        self,
        active_emotions: List[EmotionRecord],
        current_time: Optional[datetime] = None,
    ) -> List[EmotionalConflict]:
        """
        Scans active emotion pool for pairwise contradictions across:
        - VALENCE_OPPOSITION (e.g. Happiness vs Sadness, Affection vs Anger)
        - MOTIVATIONAL_INTERFERENCE (e.g. Approach vs Avoidance)
        - SOCIAL_AMBIVALENCE (e.g. Trust vs Fear)
        Persists active conflicts to emotion_conflicts table.
        """
        now = current_time or datetime.now(timezone.utc)
        now_iso = now.isoformat()
        conflicts: List[EmotionalConflict] = []

        if len(active_emotions) < 2:
            return conflicts

        for i in range(len(active_emotions)):
            for j in range(i + 1, len(active_emotions)):
                ea = active_emotions[i]
                eb = active_emotions[j]

                def_a = EMOTION_REGISTRY.get(ea.category_name)
                def_b = EMOTION_REGISTRY.get(eb.category_name)
                if not def_a or not def_b:
                    continue

                category: Optional[ConflictCategory] = None
                weight = 0.85

                # 1. Direct Valence Opposition (one high positive, one high negative)
                if (def_a.valence >= 0.25 and def_b.valence <= -0.25) or (def_a.valence <= -0.25 and def_b.valence >= 0.25):
                    category = ConflictCategory.VALENCE_OPPOSITION
                    weight = 1.0

                # 2. Social Ambivalence (e.g. Affection + Anger or Trust + Fear)
                names = {def_a.name.upper(), def_b.name.upper()}
                if names in ({"AFFECTION", "ANGER"}, {"TRUST", "FEAR"}, {"TRUST", "ANGER"}):
                    category = ConflictCategory.SOCIAL_AMBIVALENCE
                    weight = 0.95

                # 3. Motivational Interference (Approach vs Avoidance)
                is_approach_a = (def_a.arousal >= 0.4 and def_a.dominance >= 0.3)
                is_avoid_b = (def_b.valence <= -0.5 and def_b.dominance <= -0.2)
                is_approach_b = (def_b.arousal >= 0.4 and def_b.dominance >= 0.3)
                is_avoid_a = (def_a.valence <= -0.5 and def_a.dominance <= -0.2)
                if (is_approach_a and is_avoid_b) or (is_approach_b and is_avoid_a):
                    if not category:
                        category = ConflictCategory.MOTIVATIONAL_INTERFERENCE
                        weight = 0.90

                if category is not None:
                    # Bimodal tension metric formulation (Part 1.8)
                    min_i = min(ea.current_intensity, eb.current_intensity)
                    tension = max(0.0, min(1.0, round(2.0 * min_i * weight, 4)))

                    conflict = EmotionalConflict(
                        emotion_a_id=ea.emotion_id,
                        emotion_b_id=eb.emotion_id,
                        conflict_category=category,
                        tension_metric=tension,
                        is_active=True,
                        detected_at=now,
                    )
                    conflicts.append(conflict)

                    # Persist to database
                    with self.factory.write_transaction() as cursor:
                        cursor.execute(
                            """
                            INSERT INTO emotion_conflicts (
                                conflict_id, emotion_a_id, emotion_b_id, conflict_category,
                                tension_metric, is_active, detected_at
                            ) VALUES (?, ?, ?, ?, ?, 1, ?);
                            """,
                            (
                                str(conflict.conflict_id),
                                str(ea.emotion_id),
                                str(eb.emotion_id),
                                category.value,
                                tension,
                                now_iso,
                            ),
                        )

        return conflicts

    @staticmethod
    def calculate_overall_emotional_tension(
        active_emotions: List[EmotionRecord],
    ) -> float:
        """
        Calculates aggregate internal emotional tension:
        Delta_tension = clamp(2.0 * min(max(I_pos), max(I_neg)) * 0.9, 0.0, 1.0)
        Returns 0.0 if all active emotions share the same valence direction.
        """
        pos_intensities: List[float] = []
        neg_intensities: List[float] = []

        for e in active_emotions:
            edef = EMOTION_REGISTRY.get(e.category_name)
            if not edef:
                continue
            if edef.valence > 0.15:
                pos_intensities.append(e.current_intensity)
            elif edef.valence < -0.15:
                neg_intensities.append(e.current_intensity)

        if not pos_intensities or not neg_intensities:
            return 0.0

        max_pos = max(pos_intensities)
        max_neg = max(neg_intensities)
        raw_tension = 2.0 * min(max_pos, max_neg) * 0.90
        return max(0.0, min(1.0, round(raw_tension, 4)))

    def detect_mixed_blends(
        self,
        active_emotions: List[EmotionRecord],
        current_time: Optional[datetime] = None,
    ) -> List[MixedEmotionState]:
        """
        Identifies recognized psychological blend states from combinations of active emotions.
        Persists identified blends into emotion_mixed_states table.
        """
        now = current_time or datetime.now(timezone.utc)
        now_iso = now.isoformat()
        blends: List[MixedEmotionState] = []

        if len(active_emotions) < 2:
            return blends

        active_dict = {e.category_name.upper(): e for e in active_emotions}
        active_categories = set(active_dict.keys())

        for pattern, blend_name in CANONICAL_BLENDS.items():
            if pattern.issubset(active_categories):
                matching_records = [active_dict[cat] for cat in pattern]
                matching_ids = tuple(r.emotion_id for r in matching_records)
                
                # Coherence score based on intensity balance
                intensities = [r.current_intensity for r in matching_records]
                min_i = min(intensities)
                max_i = max(intensities)
                coherence = round(min_i / max(0.01, max_i), 4)

                mixed_state = MixedEmotionState(
                    coexisting_emotion_ids=matching_ids,
                    primary_blend_name=blend_name,
                    coherence_score=coherence,
                    observed_at=now,
                )
                blends.append(mixed_state)

                with self.factory.write_transaction() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO emotion_mixed_states (
                            mixed_state_id, coexisting_emotion_ids_json, primary_blend_name,
                            coherence_score, observed_at
                        ) VALUES (?, ?, ?, ?, ?);
                        """,
                        (
                            str(mixed_state.mixed_state_id),
                            json.dumps([str(eid) for eid in matching_ids]),
                            blend_name,
                            coherence,
                            now_iso,
                        ),
                    )

        return blends

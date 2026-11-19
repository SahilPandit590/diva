"""
Emotion Generation Module for Diva Emotion Engine v1.0.0.
Component 3 from Part 2 & Part 1.1.
Instantiates primitive and complex emotional responses from evaluated triggers.
Supports:
- Spontaneous autonomous generation during idle periods (E01).
- Internal thoughts & episodic memory triggers (E02).
- Multi-source convergence synthesis (E03).
- Single experience generating multiple simultaneous distinct emotions (E04).
- Complete causal provenance tracking (E05).
- Deduplication and idempotency verification (E29).
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple
import uuid

from emotion_engine.database.connection import DatabaseConnectionFactory
from emotion_engine.decay.manager import EmotionTransitionManager
from emotion_engine.generation.classifier import EmotionClassificationModule
from emotion_engine.ingress.handler import EmotionTriggerSignal
from emotion_engine.intensity.manager import IntensityManager
from emotion_engine.lifecycle.manager import EmotionalLifecycleManager
from emotion_engine.mood.manager import MoodManager
from emotion_engine.triggers.analyzer import EmotionalTriggerAnalyzer
from emotion_engine.types.enums import (
    EmotionState,
    EmotionType,
    TriggerSource,
)
from emotion_engine.types.models import EmotionRecord
from emotion_engine.types.registry import EMOTION_REGISTRY


class EmotionGenerationModule:
    """Orchestrates trigger appraisal, multi-source synthesis, and emotion instantiation."""

    def __init__(
        self,
        factory: DatabaseConnectionFactory,
        lifecycle: EmotionalLifecycleManager,
        mood: MoodManager,
        transitions: EmotionTransitionManager,
    ):
        self.factory = factory
        self.lifecycle = lifecycle
        self.mood = mood
        self.transitions = transitions
        self.classifier = EmotionClassificationModule()
        self._processed_event_ids: Set[str] = set()

    def is_event_processed(self, source_event_id: str) -> bool:
        """Idempotency check: verifies if source event ID was already ingested (E29)."""
        if source_event_id in self._processed_event_ids:
            return True
        with self.factory.read_cursor() as cursor:
            cursor.execute(
                "SELECT count(*) as cnt FROM emotion_triggers WHERE source_event_id = ?;",
                (source_event_id,),
            )
            count = cursor.fetchone()["cnt"]
            if count > 0:
                self._processed_event_ids.add(source_event_id)
                return True
        return False

    def process_trigger_signal(
        self,
        signal: EmotionTriggerSignal,
        current_time: Optional[datetime] = None,
    ) -> List[EmotionRecord]:
        """
        Processes an incoming trigger signal through the complete generation pipeline:
        1. Verifies idempotency (E29).
        2. Analyzes trigger significance, valence, and uncertainty.
        3. Looks up or renews matching active emotions (E14).
        4. Instantiates primary and secondary complex emotions (E04).
        5. Inscribes complete causal provenance (E05).
        """
        now = current_time or datetime.now(timezone.utc)

        # 1. Idempotency verification
        if self.is_event_processed(signal.source_event_id):
            return []
        self._processed_event_ids.add(signal.source_event_id)

        # 2. Get current mood and active emotions
        curr_mood = self.mood.get_current_mood()
        active_emotions = self.lifecycle.recover_active_emotions()

        # 3. Analyze trigger
        eval_result = EmotionalTriggerAnalyzer.evaluate_signal(
            signal=signal,
            current_mood=curr_mood,
            active_emotions=active_emotions,
        )

        categories_to_instantiate: List[str] = [eval_result.primary_category]

        # Single experience generating multiple simultaneous distinct emotions (E04)
        if eval_result.secondary_categories and eval_result.assessed_significance >= 0.40:
            categories_to_instantiate.extend(eval_result.secondary_categories)

        results: List[EmotionRecord] = []
        active_by_cat = {e.category_name.upper(): e for e in active_emotions}

        for cat_name in categories_to_instantiate:
            edef = EMOTION_REGISTRY.get(cat_name)
            if not edef:
                continue

            # Calculate multi-factor intensity
            mood_pad = (curr_mood.valence, curr_mood.arousal, curr_mood.dominance)
            intensity_calc = IntensityManager.calculate_intensity(
                category_name=cat_name,
                assessed_significance=eval_result.assessed_significance,
                current_mood_pad=mood_pad,
                personality_multiplier=1.0,
            )
            calibrated_i = intensity_calc["calibrated_intensity"]

            cat_upper = cat_name.upper()

            # 4. Renewal check (E14): if already active in pool, renew without duplicate
            if cat_upper in active_by_cat:
                existing = active_by_cat[cat_upper]
                renewed = self.transitions.renew_emotion(
                    emotion_id=existing.emotion_id,
                    boost_delta=round(calibrated_i * 0.4, 4),
                    current_time=now,
                )
                results.append(renewed)
            else:
                # 5. Create new emotion instance
                derivation = (
                    f"{signal.source_engine.value}_INGRESS",
                    "TRIGGER_ANALYZER",
                    f"GENERATION_{edef.emotion_type.value}",
                    f"INTENSITY_CALIBRATION_{intensity_calc['calibrated_intensity']:.2f}",
                )
                created = self.lifecycle.create_emotion(
                    category_name=edef.name,
                    emotion_type=edef.emotion_type,
                    initial_intensity=calibrated_i,
                    source_engine=signal.source_engine,
                    source_event_id=signal.source_event_id,
                    trigger_type=signal.trigger_type,
                    assessed_significance=eval_result.assessed_significance,
                    perceived_valence=eval_result.perceived_valence,
                    trigger_contribution=intensity_calc["trigger_contribution"],
                    mood_contribution=intensity_calc["mood_contribution"],
                    personality_multiplier=intensity_calc["personality_contribution"],
                    environmental_setting=signal.context_metadata.get("environment", "INTERNAL"),
                    social_interlocutor_id=signal.context_metadata.get("interlocutor_id"),
                    active_task_id=signal.context_metadata.get("task_id"),
                    uncertainty_score=eval_result.uncertainty_score,
                    context_metadata=eval_result.context_metadata,
                    derivation_chain=derivation,
                )
                # Boost to ACTIVE_SURGE
                surge = self.lifecycle.transition_emotion_state(
                    emotion_id=created.emotion_id,
                    new_state=EmotionState.ACTIVE_SURGE,
                    triggering_factor=f"Trigger appraisal surge ({signal.trigger_type})",
                )
                results.append(surge)
                active_by_cat[cat_upper] = surge

        # Update mood with newly created/renewed emotions
        all_active = self.lifecycle.recover_active_emotions()
        self.mood.update_mood(active_emotions=all_active, current_time=now)

        return results

    def process_multi_source_triggers(
        self,
        signals: List[EmotionTriggerSignal],
        current_time: Optional[datetime] = None,
    ) -> List[EmotionRecord]:
        """
        Multi-source synthesis (Checkpoint E03):
        Simultaneous convergence of diverse triggers (e.g. Memory recall + Perception observation)
        synthesizes an amplified, multi-faceted emotional response.
        """
        if not signals:
            return []

        if len(signals) == 1:
            return self.process_trigger_signal(signals[0], current_time=current_time)

        now = current_time or datetime.now(timezone.utc)
        curr_mood = self.mood.get_current_mood()

        # Combine trigger sources and amplify significance
        combined_sig = min(1.0, sum(s.assessed_significance for s in signals) * 0.75)
        avg_valence = sum(s.perceived_valence for s in signals) / len(signals)
        combined_sources = "+".join(s.source_engine.value for s in signals)
        combined_event_id = f"MULTI-{uuid.uuid4().hex[:8]}"

        # Synthesize composite trigger
        composite_signal = EmotionTriggerSignal(
            source_engine=signals[0].source_engine,
            source_event_id=combined_event_id,
            trigger_type="MULTI_SOURCE_SYNTHESIS",
            raw_content=f"Convergent multi-source stimuli from: {combined_sources}",
            assessed_significance=combined_sig,
            perceived_valence=avg_valence,
            confidence=min(s.confidence for s in signals),
            context_metadata={"sources": [s.source_engine.value for s in signals]},
            received_at=now,
        )

        return self.process_trigger_signal(composite_signal, current_time=current_time)

    def generate_autonomous_idle_emotion(
        self,
        current_time: Optional[datetime] = None,
    ) -> Optional[EmotionRecord]:
        """
        Spontaneous Autonomous Emergence (Checkpoint E01 & Part 1.1 Pathway 8):
        Generates emotional states autonomously without external user interaction during idle periods.
        Instantiates mild Curiosity or reflective Interest based on internal state.
        """
        now = current_time or datetime.now(timezone.utc)
        curr_mood = self.mood.get_current_mood()

        # Autonomous emergence creates an internal epistemic trigger
        event_id = f"SPONTANEOUS-{uuid.uuid4().hex[:8]}"
        category = "Curiosity" if curr_mood.valence >= 0.0 else "Nostalgia"

        signal = EmotionTriggerSignal(
            source_engine=TriggerSource.SPONTANEOUS,
            source_event_id=event_id,
            trigger_type="AUTONOMOUS_IDLE_EMERGENCE",
            raw_content="Endogenous affective shift during cognitive idle period.",
            assessed_significance=0.45,
            perceived_valence=0.40 if category == "Curiosity" else 0.10,
            confidence=0.90,
            context_metadata={"idle_tick": True},
            received_at=now,
        )

        results = self.process_trigger_signal(signal, current_time=current_time)
        return results[0] if results else None

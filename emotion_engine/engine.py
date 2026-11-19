"""
Diva Cognitive Architecture — Engine 11: Emotion Engine.
Master Unified Facade orchestrating all twelve internal components,
persistence, temporal decay, circumplex mood integration, conflict management,
and inter-engine communication contracts.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid

from emotion_engine.conflict.manager import EmotionalConflictManager
from emotion_engine.contracts.interfaces import (
    AttentionContract,
    CognitiveIntegrationContract,
    EmotionalStateSnapshot,
    MemoryContract,
    MemoryNomination,
    MotivationContract,
    PersonalityContract,
    ThoughtContract,
)
from emotion_engine.database.connection import DatabaseConnectionFactory
from emotion_engine.database.migrations import MigrationRunner
from emotion_engine.decay.manager import EmotionTransitionManager
from emotion_engine.generation.module import EmotionGenerationModule
from emotion_engine.ingress.handler import (
    EmotionInputHandler,
    EmotionTriggerSignal,
)
from emotion_engine.learning.interface import (
    EmotionalLearningInterface,
    OwnerApplicationReceipt,
    ParameterChangeRequest,
)
from emotion_engine.lifecycle.manager import EmotionalLifecycleManager
from emotion_engine.mood.manager import MoodManager
from emotion_engine.regulation.module import EmotionRegulationModule
from emotion_engine.tendencies.manager import EmotionalTendencyManager
from emotion_engine.types.enums import (
    EmotionState,
    EmotionType,
    RegulationStrategyType,
    TriggerSource,
)
from emotion_engine.types.models import (
    EmotionRecord,
    EmotionalConflict,
    EmotionalTendency,
    MixedEmotionState,
    MoodRecord,
    RegulationRecord,
)


class EmotionEngine:
    """Master authority and coordinating facade for Diva's affective life."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self.factory = DatabaseConnectionFactory(db_path)
        self.migrations = MigrationRunner(self.factory)
        self.migrations.apply_migrations()

        # Component 12: Lifecycle Manager
        self.lifecycle = EmotionalLifecycleManager(self.factory)

        # Component 6: Transition & Decay Manager
        self.transitions = EmotionTransitionManager(self.factory, self.lifecycle)

        # Component 7: Circumplex Mood Manager
        self.mood = MoodManager(self.factory, self.lifecycle)

        # Component 8: Conflict & Ambivalence Manager
        self.conflicts = EmotionalConflictManager(self.factory, self.lifecycle)

        # Component 1 & 2: Ingress & Trigger Analysis
        self.input_handler = EmotionInputHandler()

        # Component 3 & 4: Generation & Classification Module
        self.generation = EmotionGenerationModule(
            factory=self.factory,
            lifecycle=self.lifecycle,
            mood=self.mood,
            transitions=self.transitions,
        )

        # Component 9: Regulation Module
        self.regulation = EmotionRegulationModule(self.factory, self.lifecycle)

        # Component 10: Tendency Manager
        self.tendencies = EmotionalTendencyManager(self.factory, self.lifecycle)

        # Component 11: Learning Engine Interface
        self.learning = EmotionalLearningInterface(self.factory, self.tendencies)

        # Memory nominations queue (Contract 2)
        self._memory_nominations: List[MemoryNomination] = []

    def submit_trigger(
        self,
        source_engine: TriggerSource,
        source_event_id: str,
        trigger_type: str,
        assessed_significance: float,
        perceived_valence: float,
        raw_content: str = "",
        confidence: float = 1.0,
        context_metadata: Optional[Dict[str, Any]] = None,
        current_time: Optional[datetime] = None,
    ) -> List[EmotionRecord]:
        """
        Public ingress API: receives an emotional trigger from any connected engine,
        evaluates affective significance, and generates or renews active emotions.
        """
        signal = self.input_handler.create_signal(
            source_engine=source_engine,
            source_event_id=source_event_id,
            trigger_type=trigger_type,
            assessed_significance=assessed_significance,
            perceived_valence=perceived_valence,
            raw_content=raw_content,
            confidence=confidence,
            context_metadata=context_metadata,
            received_at=current_time,
        )
        return self.generation.process_trigger_signal(signal, current_time=current_time)

    def get_active_emotions(self) -> List[EmotionRecord]:
        """Returns all currently active (non-extinct) emotion instances."""
        return self.lifecycle.recover_active_emotions()

    def get_current_mood(self) -> MoodRecord:
        """Returns active 3D circumplex mood record."""
        return self.mood.get_current_mood()

    def get_emotional_tension(self) -> float:
        """Computes current internal emotional tension metric (Delta_tension)."""
        active = self.get_active_emotions()
        return self.conflicts.calculate_overall_emotional_tension(active)

    def get_emotional_state_snapshot(self) -> EmotionalStateSnapshot:
        """
        Transmits authoritative state snapshot to Cognitive Integration Engine (Contract 10).
        Modulates speech prosody, hesitation, warmth, and decision priorities.
        """
        active = self.get_active_emotions()
        mood = self.get_current_mood()
        conflicts = self.conflicts.detect_conflicts(active)
        tension = self.conflicts.calculate_overall_emotional_tension(active)

        return CognitiveIntegrationContract.build_snapshot(
            active_emotions=active,
            mood=mood,
            tension=tension,
            conflicts_count=len(conflicts),
        )

    def tick(
        self,
        elapsed_seconds: float = 1.0,
        current_time: Optional[datetime] = None,
        auto_regulate_surges: bool = True,
    ) -> Dict[str, Any]:
        """
        Executes a continuous dynamical tick pass:
        1. Decays active emotions exponentially toward homeostatic baselines.
        2. Integrates active emotional pull into background circumplex mood.
        3. Identifies ambivalent conflicts and emergent mixed emotion blends.
        4. Auto-regulates acute surges (I >= 0.90) to maintain cognitive stability.
        5. Nominates high-significance events (S >= 0.75) for episodic memory consolidation.
        """
        now = current_time or datetime.now(timezone.utc)

        # 1. Decay active emotions
        decay_result = self.transitions.decay_active_emotions(current_time=now)

        # 2. Update persistent mood
        active_emotions = self.get_active_emotions()
        updated_mood = self.mood.update_mood(
            active_emotions=active_emotions,
            elapsed_seconds=elapsed_seconds,
            current_time=now,
        )

        # 3. Detect conflicts & mixed blends
        conflicts = self.conflicts.detect_conflicts(active_emotions, current_time=now)
        blends = self.conflicts.detect_mixed_blends(active_emotions, current_time=now)
        tension = self.conflicts.calculate_overall_emotional_tension(active_emotions)

        # 4. Auto-regulate acute surges (I >= 0.90)
        regulated_records: List[RegulationRecord] = []
        if auto_regulate_surges:
            for emotion in active_emotions:
                if emotion.current_intensity >= 0.90 and emotion.state != EmotionState.REGULATING:
                    reg = self.regulation.regulate_emotion(
                        emotion_id=emotion.emotion_id,
                        current_time=now,
                    )
                    regulated_records.append(reg)

        # 5. Check for high-significance memory nominations (S >= 0.75, E26)
        for emotion in active_emotions:
            with self.factory.read_cursor() as cursor:
                cursor.execute(
                    "SELECT assessed_significance FROM emotion_triggers WHERE emotion_id = ?;",
                    (str(emotion.emotion_id),),
                )
                t_row = cursor.fetchone()
                sig = t_row["assessed_significance"] if t_row else emotion.current_intensity

            if sig >= 0.75:
                nom = MemoryContract.create_nomination(
                    emotion=emotion,
                    significance=sig,
                    mood=updated_mood,
                    derivation=("EMOTION_ENGINE", emotion.category_name, f"SIGNIFICANCE_{sig:.2f}"),
                )
                if nom and not any(n.emotion_id == nom.emotion_id for n in self._memory_nominations):
                    self._memory_nominations.append(nom)

        # Check Attention Control alert (Contract 7)
        attention_alert = AttentionContract.evaluate_attention_alert(active_emotions)

        return {
            "timestamp": now.isoformat(),
            "active_emotions_count": len(active_emotions),
            "decay_pass": decay_result.model_dump(mode="json"),
            "mood_vector": (updated_mood.valence, updated_mood.arousal, updated_mood.dominance),
            "mood_label": updated_mood.label_descriptor,
            "conflicts_detected": len(conflicts),
            "blends_detected": len(blends),
            "tension_metric": tension,
            "regulated_count": len(regulated_records),
            "attention_alert": attention_alert,
        }

    def regulate_emotion(
        self,
        emotion_id: uuid.UUID,
        strategy_type: Optional[RegulationStrategyType] = None,
        current_time: Optional[datetime] = None,
    ) -> RegulationRecord:
        """Executes explicit emotional regulation on an active emotion instance."""
        return self.regulation.regulate_emotion(
            emotion_id=emotion_id,
            strategy_type=strategy_type,
            current_time=current_time,
        )

    def apply_learning_parameter_change(
        self,
        request: ParameterChangeRequest,
        current_time: Optional[datetime] = None,
    ) -> OwnerApplicationReceipt:
        """Applies owner-directed parameter change request from Learning Engine v2.5.0."""
        return self.learning.apply_parameter_change(request, current_time=current_time)

    def generate_autonomous_idle_emotion(
        self,
        current_time: Optional[datetime] = None,
    ) -> Optional[EmotionRecord]:
        """Spontaneous affective emergence during idle periods (E01)."""
        return self.generation.generate_autonomous_idle_emotion(current_time=current_time)

    def get_pending_memory_nominations(self) -> List[MemoryNomination]:
        """Retrieves and clears pending high-significance episodic memory nominations."""
        noms = list(self._memory_nominations)
        self._memory_nominations.clear()
        return noms

    def close(self) -> None:
        """Closes all underlying SQLite resources."""
        self.factory.close()

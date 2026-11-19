"""
Inter-Engine Communication Contracts for Diva Emotion Engine v1.0.0.
Part 3 from the specification.
Strongly-typed contracts for all 10 connected engines:
1. Perception Engine
2. Memory Engine
3. Thought Engine
4. Motivation Engine
5. Learning Engine (see emotion_engine.learning)
6. Personality Engine
7. Attention Control
8. Energy Regulation
9. Social Cognition
10. Cognitive Integration & Decision Engine
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid
from pydantic import BaseModel, ConfigDict, Field

from emotion_engine.types.models import EmotionRecord, MoodRecord


class EmotionalStateSnapshot(BaseModel):
    """
    Master state snapshot transmitted to Cognitive Integration Engine (Contract 10).
    Modulates speech prosody, conversational delivery, and decision weighting.
    """
    model_config = ConfigDict(frozen=True)

    snapshot_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    active_emotions: Tuple[EmotionRecord, ...]
    dominant_emotion: Optional[EmotionRecord] = None
    mood_vector: Tuple[float, float, float]  # <V, A, D>
    mood_label: str
    emotional_tension: float = Field(ge=0.0, le=1.0)
    active_conflicts_count: int = Field(ge=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MemoryNomination(BaseModel):
    """
    Episodic memory nomination transmitted to Memory Engine (Contract 2 & Part 1.12).
    Triggered when an emotional experience exceeds significance threshold (S >= 0.75).
    """
    model_config = ConfigDict(frozen=True)

    nomination_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    emotion_id: uuid.UUID
    category: str
    significance: float = Field(ge=0.75, le=1.0)
    peak_intensity: float = Field(ge=0.0, le=1.0)
    mood_snapshot: Tuple[float, float, float]
    derivation_chain: Tuple[str, ...] = Field(default_factory=tuple)
    nominated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PerceptionContract:
    """Contract 1: Ingress from Perception Engine."""
    @staticmethod
    def format_perception_trigger(
        event_id: str,
        trigger_type: str,
        significance: float,
        valence: float,
        prosody_markers: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "source_engine": "PERCEPTION",
            "source_event_id": event_id,
            "trigger_type": trigger_type,
            "assessed_significance": significance,
            "perceived_valence": valence,
            "context_metadata": {"prosody": prosody_markers or {}},
        }


class MemoryContract:
    """Contract 2: Interface with Memory Engine."""
    @staticmethod
    def create_nomination(
        emotion: EmotionRecord,
        significance: float,
        mood: MoodRecord,
        derivation: Tuple[str, ...],
    ) -> Optional[MemoryNomination]:
        """Nominates high-significance emotional events (S >= 0.75) for consolidation."""
        if significance < 0.75:
            return None
        return MemoryNomination(
            emotion_id=emotion.emotion_id,
            category=emotion.category_name,
            significance=significance,
            peak_intensity=emotion.current_intensity,
            mood_snapshot=(mood.valence, mood.arousal, mood.dominance),
            derivation_chain=derivation,
        )


class ThoughtContract:
    """Contract 3: Ingress and affective resonance with Thought Engine."""
    @staticmethod
    def compute_thought_resonance(active_emotions: List[EmotionRecord]) -> Dict[str, float]:
        """Dispatches affective resonance vector weighting heuristic thought search."""
        return {e.category_name: e.current_intensity for e in active_emotions}


class MotivationContract:
    """Contract 4: Affective drive modulation with Motivation Engine."""
    @staticmethod
    def compute_motivational_modulation(active_emotions: List[EmotionRecord]) -> Dict[str, float]:
        """Dispatches emotional intensity vectors that amplify or dampen drive strength."""
        amplifiers: Dict[str, float] = {}
        for e in active_emotions:
            cat = e.category_name.upper()
            if cat in ("CURIOSITY", "INTEREST", "ANTICIPATION", "EXCITEMENT"):
                amplifiers["EXPLORATION_DRIVE"] = amplifiers.get("EXPLORATION_DRIVE", 1.0) + (e.current_intensity * 0.4)
            elif cat in ("FRUSTRATION", "ANGER"):
                amplifiers["DETERMINATION_OR_PIVOT"] = amplifiers.get("DETERMINATION_OR_PIVOT", 1.0) + (e.current_intensity * 0.3)
            elif cat in ("FEAR", "DISTRESS"):
                amplifiers["PROTECTIVE_CAUTION"] = amplifiers.get("PROTECTIVE_CAUTION", 1.0) + (e.current_intensity * 0.5)
        return amplifiers


class PersonalityContract:
    """Contract 6: Read-only constitutional baseline consumption from Personality Engine."""
    @staticmethod
    def format_read_only_modulators(
        openness: float = 0.8,
        conscientiousness: float = 0.8,
        extraversion: float = 0.7,
        agreeableness: float = 0.85,
        neuroticism: float = 0.3,
    ) -> Dict[str, float]:
        """Provides personality multipliers without directly mutating personality parameters (E34)."""
        return {
            "curiosity_mod": 0.8 + (openness * 0.4),
            "empathy_mod": 0.7 + (agreeableness * 0.5),
            "resilience_mod": 1.2 - (neuroticism * 0.5),
        }


class AttentionContract:
    """Contract 7: High-intensity emotional alerts to Attention Control."""
    @staticmethod
    def evaluate_attention_alert(active_emotions: List[EmotionRecord]) -> Optional[Dict[str, Any]]:
        """Dispatches high-intensity emotional alert (I >= 0.85) requesting global focus."""
        critical = [e for e in active_emotions if e.current_intensity >= 0.85]
        if not critical:
            return None
        strongest = max(critical, key=lambda x: x.current_intensity)
        return {
            "attention_interrupt_requested": True,
            "target_emotion_id": str(strongest.emotion_id),
            "category": strongest.category_name,
            "intensity": strongest.current_intensity,
            "priority": "HIGH",
        }


class EnergyContract:
    """Contract 8: Ingests cognitive/physiological energy from Energy Regulation."""
    @staticmethod
    def compute_energy_arousal_cap(cognitive_energy: float) -> float:
        """Low energy biases mood and limits maximum arousal capacity."""
        cog_e = max(0.0, min(1.0, cognitive_energy))
        # Arousal cap scales between 0.30 (fatigued) and 1.0 (energetic)
        return 0.30 + (0.70 * cog_e)


class SocialCognitionContract:
    """Contract 9: Ingress from Social Cognition Engine."""
    @staticmethod
    def format_social_trigger(
        interlocutor_id: str,
        rapport_score: float,
        perceived_trust: float,
        social_event_type: str,
    ) -> Dict[str, Any]:
        return {
            "source_engine": "SOCIAL",
            "source_event_id": f"SOC-{uuid.uuid4().hex[:8]}",
            "trigger_type": social_event_type,
            "assessed_significance": max(0.3, min(1.0, rapport_score)),
            "perceived_valence": max(-1.0, min(1.0, (perceived_trust - 0.5) * 2.0)),
            "context_metadata": {"interlocutor_id": interlocutor_id, "rapport": rapport_score},
        }


class CognitiveIntegrationContract:
    """Contract 10: State snapshot transmission to Cognitive Integration Engine."""
    @staticmethod
    def build_snapshot(
        active_emotions: List[EmotionRecord],
        mood: MoodRecord,
        tension: float,
        conflicts_count: int,
    ) -> EmotionalStateSnapshot:
        dominant = max(active_emotions, key=lambda x: x.current_intensity) if active_emotions else None
        return EmotionalStateSnapshot(
            active_emotions=tuple(active_emotions),
            dominant_emotion=dominant,
            mood_vector=(mood.valence, mood.arousal, mood.dominance),
            mood_label=mood.label_descriptor,
            emotional_tension=tension,
            active_conflicts_count=conflicts_count,
        )

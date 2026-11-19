"""
Emotional Trigger Analyzer for Diva Emotion Engine v1.0.0.
Component 2 from Part 2 & Part 1.7.
Evaluates affective relevance, situational novelty, and contextual valence.
Preserves mathematical uncertainty (E24) and contextual ambiguity without forcing binary labels (E10).
"""

from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field

from emotion_engine.ingress.handler import EmotionTriggerSignal
from emotion_engine.types.enums import TriggerSource
from emotion_engine.types.models import EmotionRecord, MoodRecord
from emotion_engine.types.registry import EMOTION_REGISTRY


class TriggerEvaluationResult(BaseModel):
    """Evaluated affective appraisal of an incoming trigger signal."""
    model_config = ConfigDict(frozen=True)

    signal: EmotionTriggerSignal
    primary_category: str
    secondary_categories: Tuple[str, ...] = Field(default_factory=tuple)
    assessed_significance: float = Field(ge=0.0, le=1.0)
    perceived_valence: float = Field(ge=-1.0, le=1.0)
    uncertainty_score: float = Field(ge=0.0, le=1.0)
    context_metadata: Dict[str, Any] = Field(default_factory=dict)


# Mapping trigger categories and patterns to candidate emotional archetypes
TRIGGER_ARCHETYPE_RULES: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "ACHIEVEMENT": ("Happiness", ("Pride", "Joy")),
    "USER_COMPLIMENT": ("Happiness", ("Gratitude", "Pride")),
    "LOSS": ("Sadness", ()),
    "DISAPPOINTMENT": ("Sadness", ("Disappointment",)),
    "OBSTRUCTION": ("Anger", ("Frustration",)),
    "THREAT": ("Fear", ()),
    "DANGER": ("Fear", ("Anxiety",)),
    "SUDDEN_EVENT": ("Surprise", ()),
    "NOVEL_PUZZLE": ("Curiosity", ("Interest",)),
    "EXPLORATION": ("Interest", ("Curiosity", "Anticipation")),
    "DISCOVERY": ("Curiosity", ("Interest", "Joy")),
    "WARMTH": ("Affection", ("Trust",)),
    "SOCIAL_BOND": ("Affection", ("Trust", "Gratitude")),
    "OVERWHELM": ("Distress", ()),
    "ANTICIPATION": ("Anticipation", ("Hope",)),
    "NOSTALGIA": ("Sadness", ("Affection", "Nostalgia")),
    "RECALL": ("Nostalgia", ("Gratitude", "Affection")),
    "BITTERSWEET": ("Happiness", ("Sadness", "Nostalgia")),
    "GRADUATION": ("Happiness", ("Sadness", "Nostalgia")),
    "SIMULATION": ("Anxiety", ("Fear", "Anticipation")),
    "COUNTERFACTUAL": ("Anxiety", ("Fear", "Anticipation")),
    "AESTHETIC_RESONANCE": ("Interest", ("Happiness",)),
    "AUTONOMOUS": ("Curiosity", ("Interest",)),
    "IDLE": ("Curiosity", ("Interest",)),
}


class EmotionalTriggerAnalyzer:
    """Evaluates affective significance and extracts candidate emotional activations."""

    @staticmethod
    def evaluate_historical_association(associations: List[Dict[str, Any]]) -> float:
        """Computes affective resonance boost from historical memory associations (E23)."""
        if not associations:
            return 0.0
        total_boost = 0.0
        for assoc in associations:
            intensity = float(assoc.get("intensity", 0.5))
            valence = float(assoc.get("valence", 0.0))
            total_boost += (intensity * 0.2) + (abs(valence) * 0.1)
        return round(min(0.5, total_boost / len(associations)), 4)

    @classmethod
    def evaluate_signal(
        cls,
        signal: EmotionTriggerSignal,
        current_mood: Optional[MoodRecord] = None,
        active_emotions: Optional[List[EmotionRecord]] = None,
    ) -> TriggerEvaluationResult:
        """
        Evaluates trigger signal against current mood context and existing emotional activations.
        Calculates mathematical uncertainty: U = max(0.0, 1.0 - confidence) (E24).
        """
        uncertainty = max(0.0, min(1.0, round(1.0 - signal.confidence, 4)))

        # Explicit uncertainty from context if present
        if "uncertainty" in signal.context_metadata:
            ctx_u = float(signal.context_metadata["uncertainty"])
            uncertainty = max(uncertainty, ctx_u)

        trigger_type_key = signal.trigger_type.upper()
        
        # Check rule mapping
        matched_rule = None
        for key, (prim, sec) in TRIGGER_ARCHETYPE_RULES.items():
            if key in trigger_type_key:
                matched_rule = (prim, sec)
                break

        if matched_rule:
            primary_cat, sec_cats = matched_rule
        else:
            # Fallback based on perceived valence and source
            if signal.source_engine == TriggerSource.THOUGHT:
                primary_cat = "Curiosity" if signal.perceived_valence >= 0.0 else "Distress"
                sec_cats = ("Interest",) if signal.perceived_valence >= 0.0 else ()
            elif signal.source_engine == TriggerSource.SOCIAL:
                primary_cat = "Trust" if signal.perceived_valence >= 0.0 else "Fear"
                sec_cats = ("Affection",) if signal.perceived_valence >= 0.0 else ("Anger",)
            elif signal.source_engine == TriggerSource.MEMORY:
                primary_cat = "Affection" if signal.perceived_valence >= 0.0 else "Sadness"
                sec_cats = ("Nostalgia",)
            else:
                primary_cat = "Happiness" if signal.perceived_valence >= 0.0 else "Sadness"
                sec_cats = ()

        # Context enrichment and multi-factor significance modulation (E22)
        enriched_ctx = dict(signal.context_metadata)
        enriched_ctx["source_engine"] = signal.source_engine.value
        enriched_ctx["raw_trigger_type"] = signal.trigger_type
        if current_mood:
            enriched_ctx["baseline_mood_label"] = current_mood.label_descriptor

        relational_boost = float(signal.context_metadata.get("relational_significance", 0.0)) * 0.15
        goal_boost = float(signal.context_metadata.get("goal_congruence", 0.0)) * 0.10
        adjusted_sig = max(0.0, min(1.0, round(signal.assessed_significance + relational_boost + goal_boost, 4)))

        return TriggerEvaluationResult(
            signal=signal,
            primary_category=primary_cat,
            secondary_categories=sec_cats,
            assessed_significance=adjusted_sig,
            perceived_valence=signal.perceived_valence,
            uncertainty_score=uncertainty,
            context_metadata=enriched_ctx,
        )

    @classmethod
    def evaluate_trigger(
        cls,
        signal: EmotionTriggerSignal,
        current_mood: Optional[MoodRecord] = None,
        active_emotions: Optional[List[EmotionRecord]] = None,
    ) -> TriggerEvaluationResult:
        """Alias for evaluate_signal."""
        return cls.evaluate_signal(signal, current_mood=current_mood, active_emotions=active_emotions)

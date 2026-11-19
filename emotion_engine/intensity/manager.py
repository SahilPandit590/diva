"""
Mathematical Intensity Manager for Diva Emotion Engine v1.0.0.
Component 5 from Part 2 & Part 1.4.
Calculates calibrated intensity scores using the multi-factor formulation:
I = clamp(w_T * S_trigger + w_M * MoodAlignment + w_P * PersonalitySensitivity)
"""

from enum import Enum
import math
from typing import Dict, Optional, Tuple

from emotion_engine.types.registry import EMOTION_REGISTRY, EmotionDefinition


class IntensityTier(str, Enum):
    """Categorical intensity tiers calibrated to cognitive influence thresholds."""
    SUB_THRESHOLD = "SUB_THRESHOLD"  # [0.00, 0.15)
    MILD = "MILD"                    # [0.15, 0.40)
    MODERATE = "MODERATE"            # [0.40, 0.70)
    STRONG = "STRONG"                # [0.70, 0.90)
    ACUTE = "ACUTE"                  # [0.90, 1.00]


# Formulation Weights (Part 1.4)
WEIGHT_TRIGGER = 0.55
WEIGHT_MOOD = 0.25
WEIGHT_PERSONALITY = 0.20


class IntensityManager:
    """Manages mathematical intensity scaling, normalization, and tier calibration."""

    @staticmethod
    def get_intensity_tier(intensity: float) -> IntensityTier:
        """Maps continuous intensity in [0.0, 1.0] to psychological calibration tier."""
        if intensity < 0.15:
            return IntensityTier.SUB_THRESHOLD
        elif intensity < 0.40:
            return IntensityTier.MILD
        elif intensity < 0.70:
            return IntensityTier.MODERATE
        elif intensity < 0.90:
            return IntensityTier.STRONG
        else:
            return IntensityTier.ACUTE

    @staticmethod
    def compute_mood_alignment(
        emotion_pad: Tuple[float, float, float],
        mood_pad: Tuple[float, float, float],
    ) -> float:
        """
        Computes normalized directional alignment in PAD space between an emotion and current mood.
        Returns value in [0.0, 1.0], where 1.0 is full alignment, 0.5 is orthogonal/neutral, 0.0 is opposite.
        """
        dot = (
            emotion_pad[0] * mood_pad[0]
            + emotion_pad[1] * mood_pad[1]
            + emotion_pad[2] * mood_pad[2]
        )
        mag_e = math.sqrt(
            emotion_pad[0] ** 2 + emotion_pad[1] ** 2 + emotion_pad[2] ** 2
        )
        mag_m = math.sqrt(
            mood_pad[0] ** 2 + mood_pad[1] ** 2 + mood_pad[2] ** 2
        )

        if mag_e < 1e-6 or mag_m < 1e-6:
            # If resting neutral mood or zero PAD magnitude, alignment is neutral
            return 0.5

        cosine_sim = dot / (mag_e * mag_m)
        cosine_sim = max(-1.0, min(1.0, cosine_sim))
        return (1.0 + cosine_sim) / 2.0

    @classmethod
    def calculate_intensity(
        cls,
        category_name: str,
        assessed_significance: float,
        current_mood_pad: Tuple[float, float, float] = (0.0, 0.0, 0.0),
        personality_multiplier: float = 1.0,
    ) -> Dict[str, float]:
        """
        Calculates calibrated intensity according to the master formulation:
        I = clamp(0.55 * S_trigger + 0.25 * MoodAlignment + 0.20 * (PersonalitySensitivity / 2.0))
        """
        s_trigger = max(0.0, min(1.0, assessed_significance))
        
        # Look up PAD vector
        emotion_def: Optional[EmotionDefinition] = EMOTION_REGISTRY.get(category_name)
        if emotion_def:
            emotion_pad = (emotion_def.valence, emotion_def.arousal, emotion_def.dominance)
        else:
            emotion_pad = (0.0, 0.0, 0.0)

        mood_alignment = cls.compute_mood_alignment(emotion_pad, current_mood_pad)
        
        # Normalize personality multiplier (baseline is 1.0 -> 0.5 contribution ratio, capped at 2.0 -> 1.0)
        norm_personality = max(0.0, min(1.0, personality_multiplier / 2.0))

        trigger_contrib = WEIGHT_TRIGGER * s_trigger
        mood_contrib = WEIGHT_MOOD * mood_alignment
        personality_contrib = WEIGHT_PERSONALITY * norm_personality

        raw_intensity = trigger_contrib + mood_contrib + personality_contrib
        calibrated_intensity = max(0.0, min(1.0, round(raw_intensity, 4)))

        return {
            "calibrated_intensity": calibrated_intensity,
            "raw_intensity": round(raw_intensity, 4),
            "trigger_contribution": round(trigger_contrib, 4),
            "mood_contribution": round(mood_contrib, 4),
            "personality_contribution": round(personality_contrib, 4),
            "mood_alignment": round(mood_alignment, 4),
        }

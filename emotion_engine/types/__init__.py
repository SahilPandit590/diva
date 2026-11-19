"""
Types package for Diva Emotion Engine v1.0.0.
Exports all authoritative enumerations, data models, and emotion registry.
"""

from emotion_engine.types.enums import (
    ConflictCategory,
    DecayCurveType,
    EmotionState,
    EmotionType,
    LifecycleEntityType,
    RegulationStrategyType,
    ResolutionType,
    TriggerSource,
)
from emotion_engine.types.models import (
    ActiveEmotionState,
    EmotionContext,
    EmotionDecayProfile,
    EmotionalConflict,
    EmotionalHistory,
    EmotionalLearningRecord,
    EmotionalTendency,
    EmotionIntensity,
    EmotionProvenance,
    EmotionRecord,
    EmotionTransition,
    EmotionTrigger,
    MixedEmotionState,
    MoodHistory,
    MoodRecord,
    RegulationRecord,
    RegulationStrategy,
)
from emotion_engine.types.registry import (
    COMPLEX_EMOTIONS,
    EMOTION_REGISTRY,
    PRIMITIVE_EMOTIONS,
    EmotionDefinition,
    EmotionRegistry,
)

__all__ = [
    # Enums
    "EmotionType",
    "EmotionState",
    "TriggerSource",
    "ConflictCategory",
    "DecayCurveType",
    "RegulationStrategyType",
    "ResolutionType",
    "LifecycleEntityType",
    # Models
    "EmotionRecord",
    "ActiveEmotionState",
    "EmotionIntensity",
    "EmotionTrigger",
    "EmotionContext",
    "EmotionTransition",
    "MixedEmotionState",
    "EmotionalConflict",
    "MoodRecord",
    "MoodHistory",
    "EmotionDecayProfile",
    "RegulationRecord",
    "RegulationStrategy",
    "EmotionalTendency",
    "EmotionalLearningRecord",
    "EmotionalHistory",
    "EmotionProvenance",
    # Registry
    "EmotionDefinition",
    "EmotionRegistry",
    "EMOTION_REGISTRY",
    "PRIMITIVE_EMOTIONS",
    "COMPLEX_EMOTIONS",
]

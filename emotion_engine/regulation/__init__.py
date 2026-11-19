"""
Emotional regulation package for Diva Emotion Engine v1.0.0.
"""

from emotion_engine.regulation.strategies import (
    REGULATION_STRATEGIES,
    RegulationStrategyDefinition,
)
from emotion_engine.regulation.module import EmotionRegulationModule

__all__ = [
    "REGULATION_STRATEGIES",
    "RegulationStrategyDefinition",
    "EmotionRegulationModule",
]

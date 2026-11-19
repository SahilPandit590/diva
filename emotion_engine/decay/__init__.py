"""
Temporal dynamics and decay package for Diva Emotion Engine v1.0.0.
"""

from emotion_engine.decay.manager import (
    DecayRunResult,
    EmotionTransitionManager,
    FADING_EXTINCTION_THRESHOLD,
)

__all__ = [
    "EmotionTransitionManager",
    "DecayRunResult",
    "FADING_EXTINCTION_THRESHOLD",
]

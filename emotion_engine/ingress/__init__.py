"""
Emotion Ingress Gateway package for Diva Emotion Engine v1.0.0.
"""

from emotion_engine.ingress.handler import (
    EmotionInputHandler,
    EmotionTriggerSignal,
)

__all__ = [
    "EmotionInputHandler",
    "EmotionTriggerSignal",
]

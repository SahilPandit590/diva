"""
Mood management package for Diva Emotion Engine v1.0.0.
"""

from emotion_engine.mood.manager import (
    MoodManager,
    MOOD_INTEGRATION_RATE_ALPHA,
    MAX_SINGLE_EVENT_DELTA,
)

__all__ = [
    "MoodManager",
    "MOOD_INTEGRATION_RATE_ALPHA",
    "MAX_SINGLE_EVENT_DELTA",
]

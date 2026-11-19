"""
Lifecycle management package for Diva Emotion Engine v1.0.0.
Enforces deterministic finite state machines, active pool constraints,
and relational lifecycle audit logging.
"""

from emotion_engine.lifecycle.manager import (
    EmotionalLifecycleManager,
    InvalidEmotionStateTransitionError,
)

__all__ = [
    "EmotionalLifecycleManager",
    "InvalidEmotionStateTransitionError",
]

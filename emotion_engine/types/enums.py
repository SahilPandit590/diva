"""
Authoritative enumerations for Diva Emotion Engine v1.0.0.
Strictly defines states, categories, trigger sources, decay curve types,
regulation strategies, and conflict classes.
"""

from enum import Enum


class EmotionType(str, Enum):
    """Categorical classification of an emotional response."""
    PRIMITIVE = "PRIMITIVE"
    COMPLEX = "COMPLEX"


class EmotionState(str, Enum):
    """Lifecycle state machine stages for an active emotion instance."""
    TRIGGERED = "TRIGGERED"
    ACTIVE_SURGE = "ACTIVE_SURGE"
    SUSTAINED_DECAY = "SUSTAINED_DECAY"
    REGULATING = "REGULATING"
    EXTINCTION = "EXTINCTION"


class TriggerSource(str, Enum):
    """Origin pathways for emotional triggers."""
    PERCEPTION = "PERCEPTION"
    MEMORY = "MEMORY"
    THOUGHT = "THOUGHT"
    MOTIVATION = "MOTIVATION"
    SOCIAL = "SOCIAL"
    PHYSIOLOGICAL = "PHYSIOLOGICAL"
    SPONTANEOUS = "SPONTANEOUS"


class ConflictCategory(str, Enum):
    """Categories of emotional conflict and ambivalence."""
    VALENCE_OPPOSITION = "VALENCE_OPPOSITION"
    MOTIVATIONAL_INTERFERENCE = "MOTIVATIONAL_INTERFERENCE"
    SOCIAL_AMBIVALENCE = "SOCIAL_AMBIVALENCE"


class DecayCurveType(str, Enum):
    """Mathematical trajectory profiles for emotion attenuation."""
    EXPONENTIAL = "EXPONENTIAL"
    PIECEWISE_LINEAR = "PIECEWISE_LINEAR"
    STEP_ATTENUATED = "STEP_ATTENUATED"


class RegulationStrategyType(str, Enum):
    """Formal psychological regulation strategies."""
    COGNITIVE_REAPPRAISAL = "COGNITIVE_REAPPRAISAL"
    ATTENTIONAL_DEPLOYMENT = "ATTENTIONAL_DEPLOYMENT"
    PACING_HEURISTIC = "PACING_HEURISTIC"
    EXPRESSIVE_MODULATION = "EXPRESSIVE_MODULATION"


class ResolutionType(str, Enum):
    """Reason for an emotion instance closing and entering history."""
    NATURAL_DECAY = "NATURAL_DECAY"
    REGULATED = "REGULATED"
    OVERWRITTEN = "OVERWRITTEN"
    NOMINATED_TO_MEMORY = "NOMINATED_TO_MEMORY"


class LifecycleEntityType(str, Enum):
    """Target entity types logged in append-only state transition audit ledger."""
    EMOTION = "EMOTION"
    MOOD = "MOOD"
    REGULATION = "REGULATION"
    TENDENCY = "TENDENCY"

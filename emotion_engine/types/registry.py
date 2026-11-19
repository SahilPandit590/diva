"""
Authoritative Emotion Registry for Diva Emotion Engine v1.0.0.
Pre-registers the 12 canonical Primitive Emotions and 18 canonical Complex Emotions,
including their continuous PAD (Pleasure/Valence, Arousal, Dominance) vectors,
calibrated half-lives, and constituent blend hierarchies.
"""

from typing import Dict, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field

from emotion_engine.types.enums import DecayCurveType, EmotionType


class EmotionDefinition(BaseModel):
    """Immutable specification for a primitive or complex emotion category."""
    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Canonical emotion name")
    emotion_type: EmotionType = Field(description="Primitive or Complex")
    valence: float = Field(ge=-1.0, le=1.0, description="Pleasure / Displeasure coordinate")
    arousal: float = Field(ge=-1.0, le=1.0, description="Activation / Deactivation coordinate")
    dominance: float = Field(ge=-1.0, le=1.0, description="Control / Submissiveness coordinate")
    half_life_seconds: float = Field(gt=0.0, description="Exponential decay half-life in seconds")
    decay_curve: DecayCurveType = Field(default=DecayCurveType.EXPONENTIAL, description="Attenuation trajectory")
    description: str = Field(description="Psychological definition and appraisal condition")
    constituent_primitives: Tuple[str, ...] = Field(
        default_factory=tuple,
        description="Constituent primitive emotions for complex blends"
    )
    quiescent_baseline: float = Field(default=0.0, ge=0.0, le=1.0, description="Resting baseline intensity")


# ==============================================================================
# CANONICAL PREDEFINED PRIMITIVE EMOTIONS (12)
# ==============================================================================
PRIMITIVE_EMOTIONS: Tuple[EmotionDefinition, ...] = (
    EmotionDefinition(
        name="Happiness",
        emotion_type=EmotionType.PRIMITIVE,
        valence=0.8,
        arousal=0.5,
        dominance=0.6,
        half_life_seconds=3600.0,  # 1 hour
        description="Positive appraisal of desirable events, achievement, or pleasant conditions.",
    ),
    EmotionDefinition(
        name="Sadness",
        emotion_type=EmotionType.PRIMITIVE,
        valence=-0.7,
        arousal=-0.4,
        dominance=-0.6,
        half_life_seconds=3600.0,  # 1 hour
        description="Negative response to perceived loss, separation, disappointment, or unfulfilled states.",
    ),
    EmotionDefinition(
        name="Fear",
        emotion_type=EmotionType.PRIMITIVE,
        valence=-0.8,
        arousal=0.8,
        dominance=-0.7,
        half_life_seconds=180.0,  # 3 minutes acute spike
        description="Protective response to perceived acute danger, impending threat, or profound uncertainty.",
    ),
    EmotionDefinition(
        name="Anger",
        emotion_type=EmotionType.PRIMITIVE,
        valence=-0.6,
        arousal=0.8,
        dominance=0.7,
        half_life_seconds=180.0,  # 3 minutes acute spike
        description="Response to perceived boundary violation, obstruction, unfairness, or frustration.",
    ),
    EmotionDefinition(
        name="Disgust",
        emotion_type=EmotionType.PRIMITIVE,
        valence=-0.7,
        arousal=0.4,
        dominance=0.2,
        half_life_seconds=300.0,  # 5 minutes
        description="Aversion or visceral rejection of toxic, repulsive, or fundamentally conflicting stimuli.",
    ),
    EmotionDefinition(
        name="Surprise",
        emotion_type=EmotionType.PRIMITIVE,
        valence=0.1,
        arousal=0.9,
        dominance=0.0,
        half_life_seconds=15.0,  # 15 seconds acute reflex
        description="Acute orienting response to sudden, unexpected, or schema-violating events.",
    ),
    EmotionDefinition(
        name="Interest",
        emotion_type=EmotionType.PRIMITIVE,
        valence=0.5,
        arousal=0.5,
        dominance=0.4,
        half_life_seconds=1800.0,  # 30 minutes intellectual affect
        description="Focal attraction toward a stimulus deemed novel, meaningful, or worth exploring.",
    ),
    EmotionDefinition(
        name="Curiosity",
        emotion_type=EmotionType.PRIMITIVE,
        valence=0.6,
        arousal=0.6,
        dominance=0.5,
        half_life_seconds=1800.0,  # 30 minutes
        description="Active epistemic urge to investigate, understand mechanisms, and resolve ambiguity.",
    ),
    EmotionDefinition(
        name="Affection",
        emotion_type=EmotionType.PRIMITIVE,
        valence=0.8,
        arousal=0.3,
        dominance=0.3,
        half_life_seconds=3600.0,  # 1 hour sustained state
        description="Warm emotional bonding, tenderness, and interpersonal attachment toward an entity.",
    ),
    EmotionDefinition(
        name="Distress",
        emotion_type=EmotionType.PRIMITIVE,
        valence=-0.8,
        arousal=0.7,
        dominance=-0.5,
        half_life_seconds=300.0,  # 5 minutes
        description="Aversive response to acute cognitive overwhelm, intense discomfort, or pain.",
    ),
    EmotionDefinition(
        name="Anticipation",
        emotion_type=EmotionType.PRIMITIVE,
        valence=0.4,
        arousal=0.6,
        dominance=0.4,
        half_life_seconds=600.0,  # 10 minutes
        description="Forward-looking orienting emotion directed toward an expected future event.",
    ),
    EmotionDefinition(
        name="Trust",
        emotion_type=EmotionType.PRIMITIVE,
        valence=0.7,
        arousal=-0.2,
        dominance=0.5,
        half_life_seconds=3600.0,  # 1 hour
        description="Positive social orientation characterized by perceived safety, reliability, and security.",
    ),
)


# ==============================================================================
# CANONICAL PREDEFINED COMPLEX EMOTIONS (18)
# ==============================================================================
COMPLEX_EMOTIONS: Tuple[EmotionDefinition, ...] = (
    EmotionDefinition(
        name="Excitement",
        emotion_type=EmotionType.COMPLEX,
        valence=0.8,
        arousal=0.8,
        dominance=0.6,
        half_life_seconds=900.0,  # 15 minutes
        constituent_primitives=("Happiness", "Anticipation"),
        description="High arousal positive forward-orientation toward anticipated success.",
    ),
    EmotionDefinition(
        name="Anxiety",
        emotion_type=EmotionType.COMPLEX,
        valence=-0.7,
        arousal=0.8,
        dominance=-0.6,
        half_life_seconds=600.0,  # 10 minutes
        constituent_primitives=("Fear", "Anticipation"),
        description="Future-oriented dread, vigilance, or worry regarding uncertain negative outcomes.",
    ),
    EmotionDefinition(
        name="Frustration",
        emotion_type=EmotionType.COMPLEX,
        valence=-0.6,
        arousal=0.7,
        dominance=0.4,
        half_life_seconds=600.0,  # 10 minutes
        constituent_primitives=("Anger", "Distress"),
        description="Negative affective state resulting from an impediment or barrier to an active goal.",
    ),
    EmotionDefinition(
        name="Relief",
        emotion_type=EmotionType.COMPLEX,
        valence=0.7,
        arousal=-0.4,
        dominance=0.4,
        half_life_seconds=600.0,  # 10 minutes
        constituent_primitives=("Happiness",),
        description="Happiness following the sudden removal or cessation of an expected threat or distress.",
    ),
    EmotionDefinition(
        name="Nostalgia",
        emotion_type=EmotionType.COMPLEX,
        valence=0.3,
        arousal=-0.2,
        dominance=0.1,
        half_life_seconds=1800.0,  # 30 minutes
        constituent_primitives=("Affection", "Sadness"),
        description="Bittersweet affective state anchored in fond recollection of past experiences.",
    ),
    EmotionDefinition(
        name="Jealousy",
        emotion_type=EmotionType.COMPLEX,
        valence=-0.7,
        arousal=0.7,
        dominance=0.3,
        half_life_seconds=900.0,
        constituent_primitives=("Fear", "Anger", "Affection"),
        description="Protective anger and fear of losing a valued relationship to a third-party rival.",
    ),
    EmotionDefinition(
        name="Envy",
        emotion_type=EmotionType.COMPLEX,
        valence=-0.5,
        arousal=0.5,
        dominance=-0.2,
        half_life_seconds=900.0,
        constituent_primitives=("Sadness", "Interest"),
        description="Discontent or longing aroused by someone else's perceived possession or advantage.",
    ),
    EmotionDefinition(
        name="Gratitude",
        emotion_type=EmotionType.COMPLEX,
        valence=0.8,
        arousal=0.2,
        dominance=0.3,
        half_life_seconds=1800.0,
        constituent_primitives=("Happiness", "Affection"),
        description="Warm appreciation resulting from perceived external benevolence or unexpected kindness.",
    ),
    EmotionDefinition(
        name="Guilt",
        emotion_type=EmotionType.COMPLEX,
        valence=-0.7,
        arousal=0.5,
        dominance=-0.5,
        half_life_seconds=1800.0,
        constituent_primitives=("Distress",),
        description="Distress arising from internal responsibility attribution for a negative outcome.",
    ),
    EmotionDefinition(
        name="Shame",
        emotion_type=EmotionType.COMPLEX,
        valence=-0.8,
        arousal=0.6,
        dominance=-0.8,
        half_life_seconds=1800.0,
        constituent_primitives=("Distress",),
        description="Painful distress stemming from global negative self-evaluation and perceived inadequacy.",
    ),
    EmotionDefinition(
        name="Pride",
        emotion_type=EmotionType.COMPLEX,
        valence=0.8,
        arousal=0.6,
        dominance=0.8,
        half_life_seconds=1800.0,
        constituent_primitives=("Happiness",),
        description="Exultant positive self-attribution for an accomplishment, competence, or virtue.",
    ),
    EmotionDefinition(
        name="Loneliness",
        emotion_type=EmotionType.COMPLEX,
        valence=-0.7,
        arousal=-0.3,
        dominance=-0.6,
        half_life_seconds=3600.0,
        constituent_primitives=("Sadness",),
        description="Sadness resulting from perceived isolation or discrepancy in desired social intimacy.",
    ),
    EmotionDefinition(
        name="Compassion",
        emotion_type=EmotionType.COMPLEX,
        valence=0.2,
        arousal=0.4,
        dominance=0.2,
        half_life_seconds=1800.0,
        constituent_primitives=("Affection", "Distress"),
        description="Empathetic affective response elicited by witnessing another entity's distress.",
    ),
    EmotionDefinition(
        name="Hope",
        emotion_type=EmotionType.COMPLEX,
        valence=0.6,
        arousal=0.5,
        dominance=0.3,
        half_life_seconds=1800.0,
        constituent_primitives=("Anticipation",),
        description="Positive expectation and yearning for a favorable outcome under conditions of uncertainty.",
    ),
    EmotionDefinition(
        name="Disappointment",
        emotion_type=EmotionType.COMPLEX,
        valence=-0.6,
        arousal=-0.3,
        dominance=-0.4,
        half_life_seconds=1800.0,
        constituent_primitives=("Sadness",),
        description="Sadness resulting from the violation or non-fulfillment of a positive prior expectation.",
    ),
    EmotionDefinition(
        name="Boredom",
        emotion_type=EmotionType.COMPLEX,
        valence=-0.4,
        arousal=-0.6,
        dominance=-0.3,
        half_life_seconds=1200.0,
        constituent_primitives=("Sadness",),
        description="Low arousal state of disinterest, restlessness, and lack of engaging stimulation.",
    ),
    EmotionDefinition(
        name="Resentment",
        emotion_type=EmotionType.COMPLEX,
        valence=-0.6,
        arousal=0.5,
        dominance=0.2,
        half_life_seconds=3600.0,
        constituent_primitives=("Anger",),
        description="Persistent indignation or bitterness over an unresolved perceived injustice.",
    ),
    EmotionDefinition(
        name="Embarrassment",
        emotion_type=EmotionType.COMPLEX,
        valence=-0.5,
        arousal=0.7,
        dominance=-0.6,
        half_life_seconds=300.0,
        constituent_primitives=("Distress",),
        description="Acute distress and social self-consciousness following an awkward faux pas.",
    ),
)


class EmotionRegistry:
    """Authoritative immutable repository for all primitive and complex emotion definitions."""

    def __init__(self):
        self._registry: Dict[str, EmotionDefinition] = {}
        for p in PRIMITIVE_EMOTIONS:
            self._registry[p.name.upper()] = p
        for c in COMPLEX_EMOTIONS:
            self._registry[c.name.upper()] = c

    def get(self, name: str) -> Optional[EmotionDefinition]:
        """Look up emotion definition by case-insensitive name."""
        return self._registry.get(name.strip().upper())

    def contains(self, name: str) -> bool:
        """Checks if emotion category is defined in registry."""
        return name.strip().upper() in self._registry

    def list_primitives(self) -> Tuple[EmotionDefinition, ...]:
        """Returns all 12 primitive emotions."""
        return PRIMITIVE_EMOTIONS

    def list_complex(self) -> Tuple[EmotionDefinition, ...]:
        """Returns all 18 complex emotions."""
        return COMPLEX_EMOTIONS

    def list_all(self) -> Tuple[EmotionDefinition, ...]:
        """Returns all 30 pre-registered emotions."""
        return PRIMITIVE_EMOTIONS + COMPLEX_EMOTIONS


# Singleton global registry instance
EMOTION_REGISTRY = EmotionRegistry()

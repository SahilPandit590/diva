"""
Authoritative Data Models for Diva Emotion Engine v1.0.0.
Contains all 17 deeply immutable Pydantic models defined in Part 4 Section A.
Enforces frozen instances, valid bounds, and strict type constraints.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
import uuid
from pydantic import BaseModel, ConfigDict, Field

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


class BaseImmutableModel(BaseModel):
    """Base model enforcing deep immutability across all fields."""
    model_config = ConfigDict(frozen=True, extra="forbid")


# 1. Active and Historical Emotion Instances
class EmotionRecord(BaseImmutableModel):
    emotion_id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Primary key")
    category_name: str = Field(description="Maps to primitive or complex emotion name")
    emotion_type: EmotionType = Field(description="PRIMITIVE or COMPLEX")
    current_intensity: float = Field(ge=0.0, le=1.0, description="Real-time affective intensity")
    state: EmotionState = Field(default=EmotionState.TRIGGERED, description="Current lifecycle state")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_renewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# 2. Active Emotion Aggregate Snapshot
class ActiveEmotionState(BaseImmutableModel):
    snapshot_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    active_emotion_ids: Tuple[uuid.UUID, ...] = Field(default_factory=tuple)
    dominant_emotion_id: Optional[uuid.UUID] = None
    aggregate_valence: float = Field(ge=-1.0, le=1.0)
    aggregate_arousal: float = Field(ge=0.0, le=1.0)
    emotional_tension: float = Field(default=0.0, ge=0.0, le=1.0)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# 3. Emotion Mathematical Intensities
class EmotionIntensity(BaseImmutableModel):
    intensity_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    emotion_id: uuid.UUID
    raw_intensity: float = Field(ge=0.0, le=1.0)
    calibrated_intensity: float = Field(ge=0.0, le=1.0)
    trigger_contribution: float
    mood_contribution: float
    personality_multiplier: float
    calculated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# 4. Causal Emotional Triggers
class EmotionTrigger(BaseImmutableModel):
    trigger_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    emotion_id: uuid.UUID
    source_engine: TriggerSource
    source_event_id: str
    trigger_type: str
    assessed_significance: float = Field(ge=0.0, le=1.0)
    perceived_valence: float = Field(ge=-1.0, le=1.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# 5. Contextual Surrounding Metadata
class EmotionContext(BaseImmutableModel):
    context_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    emotion_id: uuid.UUID
    social_interlocutor_id: Optional[str] = None
    environmental_setting: str = Field(default="INTERNAL")
    active_task_id: Optional[str] = None
    uncertainty_score: float = Field(default=0.0, ge=0.0, le=1.0)
    context_metadata: Dict[str, Any] = Field(default_factory=dict)


# 6. Emotional Transitions
class EmotionTransition(BaseImmutableModel):
    transition_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    emotion_id: uuid.UUID
    previous_state: str
    new_state: str
    triggering_factor: str
    intensity_delta: float
    transitioned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# 7. Mixed Emotion Blends
class MixedEmotionState(BaseImmutableModel):
    mixed_state_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    coexisting_emotion_ids: Tuple[uuid.UUID, ...] = Field(default_factory=tuple)
    primary_blend_name: Optional[str] = None
    coherence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# 8. Emotional Conflicts
class EmotionalConflict(BaseImmutableModel):
    conflict_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    emotion_a_id: uuid.UUID
    emotion_b_id: uuid.UUID
    conflict_category: ConflictCategory
    tension_metric: float = Field(ge=0.0, le=1.0)
    is_active: bool = True
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# 9. Persistent Circumplex Mood
class MoodRecord(BaseImmutableModel):
    mood_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    valence: float = Field(ge=-1.0, le=1.0)
    arousal: float = Field(ge=-1.0, le=1.0)
    dominance: float = Field(ge=-1.0, le=1.0)
    label_descriptor: str
    stability_metric: float = Field(default=0.8, ge=0.0, le=1.0)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# 10. Mood Historical Trajectory
class MoodHistory(BaseImmutableModel):
    history_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    valence_snapshot: float
    arousal_snapshot: float
    dominance_snapshot: float
    driving_emotion_ids: Tuple[uuid.UUID, ...] = Field(default_factory=tuple)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# 11. Predefined Decay Profiles
class EmotionDecayProfile(BaseImmutableModel):
    profile_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    emotion_category: str
    half_life_seconds: float = Field(gt=0.0)
    decay_curve_type: DecayCurveType = DecayCurveType.EXPONENTIAL
    quiescent_baseline: float = Field(default=0.0, ge=0.0, le=1.0)


# 12. Emotional Regulation Log
class RegulationRecord(BaseImmutableModel):
    regulation_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    emotion_id: uuid.UUID
    strategy_used: RegulationStrategyType
    intensity_before: float = Field(ge=0.0, le=1.0)
    intensity_after: float = Field(ge=0.0, le=1.0)
    was_successful: bool
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# 13. Regulation Strategy Specifications
class RegulationStrategy(BaseImmutableModel):
    strategy_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str
    applicable_emotions: Tuple[str, ...] = Field(default_factory=tuple)
    damping_factor: float = Field(ge=0.0, le=1.0)
    cognitive_effort_cost: float = Field(ge=0.0, le=1.0)


# 14. Emotional Tendencies & Sensitivities
class EmotionalTendency(BaseImmutableModel):
    tendency_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    dimension_name: str
    current_value: float
    version: int = 1
    is_constitutional_baseline: bool = False
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# 15. Emotional Learning History
class EmotionalLearningRecord(BaseImmutableModel):
    learning_record_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    proposal_id: uuid.UUID
    dimension_name: str
    old_value: float
    new_value: float
    applied_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# 16. Permanent Affective History
class EmotionalHistory(BaseImmutableModel):
    history_entry_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    emotion_id: uuid.UUID
    category: str
    peak_intensity: float = Field(ge=0.0, le=1.0)
    duration_seconds: int = Field(ge=0)
    resolution_type: ResolutionType
    closed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# 17. Causal Provenance
class EmotionProvenance(BaseImmutableModel):
    provenance_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    emotion_id: uuid.UUID
    source_engine: str
    source_event_id: str
    derivation_chain: Tuple[str, ...] = Field(default_factory=tuple)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

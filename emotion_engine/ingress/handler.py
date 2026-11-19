"""
Emotion Input Handler for Diva Emotion Engine v1.0.0.
Component 1 from Part 2 & Part 1.1.
Ingress gateway receiving external observations, thought reflections,
memory recalls, and motivational signals. Normalizes payloads into standardized
EmotionTriggerSignal envelopes.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field

from emotion_engine.types.enums import TriggerSource


class EmotionTriggerSignal(BaseModel):
    """Normalized standardized envelope for all incoming emotional stimuli."""
    model_config = ConfigDict(frozen=True)

    signal_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    source_engine: TriggerSource
    source_event_id: str
    trigger_type: str
    raw_content: str = Field(default="")
    assessed_significance: float = Field(ge=0.0, le=1.0)
    perceived_valence: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    context_metadata: Dict[str, Any] = Field(default_factory=dict)
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EmotionInputHandler:
    """Normalizes and validates multi-source emotional ingress signals."""

    @staticmethod
    def create_signal(
        source_engine: TriggerSource,
        source_event_id: str,
        trigger_type: str,
        assessed_significance: float,
        perceived_valence: float,
        raw_content: str = "",
        confidence: float = 1.0,
        context_metadata: Optional[Dict[str, Any]] = None,
        received_at: Optional[datetime] = None,
    ) -> EmotionTriggerSignal:
        """Constructs an immutable, normalized EmotionTriggerSignal envelope."""
        now = received_at or datetime.now(timezone.utc)
        sig = max(0.0, min(1.0, assessed_significance))
        val = max(-1.0, min(1.0, perceived_valence))
        conf = max(0.0, min(1.0, confidence))

        return EmotionTriggerSignal(
            source_engine=source_engine,
            source_event_id=str(source_event_id),
            trigger_type=trigger_type.strip().upper(),
            raw_content=raw_content.strip(),
            assessed_significance=sig,
            perceived_valence=val,
            confidence=conf,
            context_metadata=context_metadata or {},
            received_at=now,
        )

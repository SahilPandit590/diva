"""
Experience and intake event data contracts for Diva Memory Engine v3.0.
"""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

from memory_engine.types.enums import (
    DevelopmentStatus,
    DomainPartition,
    RetentionStatus,
    ValidityStatus,
)


class InputEvent(BaseModel):
    """
    Immutable raw signal record captured at intake.
    Stored in input_events table; never modified once written.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID
    source_engine: str
    channel: str
    domain_partition: DomainPartition = DomainPartition.COGNITIVE
    session_id: UUID
    raw_content: str
    content_hash: str
    received_at: datetime
    processed: bool = False
    processing_job_id: UUID | None = None
    schema_version: int = 1


class Experience(BaseModel):
    """
    Canonical episodic memory record in experiences table.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    experience_id: UUID
    source_event_id: UUID | None = None
    session_id: UUID
    domain_partition: DomainPartition = DomainPartition.COGNITIVE
    experience_summary: str
    participants: tuple[UUID, ...] = ()
    world_time_start: datetime | None = None
    world_time_end: datetime | None = None
    diva_time_recorded: datetime
    development_status: DevelopmentStatus = DevelopmentStatus.RAW
    validity_status: ValidityStatus = ValidityStatus.CURRENT
    retention_status: RetentionStatus = RetentionStatus.ACTIVE
    permanent_importance: float = Field(default=0.5, ge=0.0, le=1.0)
    temporary_importance: float = Field(default=0.0, ge=0.0, le=1.0)
    access_count: int = 0
    last_accessed_at: datetime | None = None
    provenance_hash: str
    schema_version: int = 1


class ExperiencePayload(BaseModel):
    """
    Full structured payload for an experience record.
    Stored separately to keep experiences table lean for indexing.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    payload_id: UUID
    experience_id: UUID
    payload_format: str = "JSON"
    payload_data: bytes
    content_hash: str
    created_at: datetime
    is_archived: bool = False
    archive_path: str | None = None

"""
Memory representation and lineage contracts for Diva Memory Engine v3.0.
"""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict

from memory_engine.types.enums import (
    DevelopmentStatus,
    DomainPartition,
    RepresentationType,
    ValidityStatus,
)


class MemoryRepresentation(BaseModel):
    """
    Structured interpretation, generalized pattern, or consolidated abstraction.
    Does NOT erase or overwrite prior versions; new versions link to parent_representation_id.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    representation_id: UUID
    source_experience_id: UUID | None = None
    parent_representation_id: UUID | None = None
    representation_type: RepresentationType
    development_status: DevelopmentStatus
    validity_status: ValidityStatus
    domain_partition: DomainPartition
    content: str
    content_hash: str
    producing_engine: str
    producing_method: str = "DETERMINISTIC"
    version: int = 1
    created_at: datetime
    superseded_at: datetime | None = None
    claims_derived: tuple[UUID, ...] = ()


class RepresentationLineage(BaseModel):
    """
    Explicit node in the derivation lineage tree of a representation.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    lineage_id: UUID
    representation_id: UUID
    parent_id: UUID | None = None
    lineage_depth: int = 0
    derivation_type: str = "VERSIONED_UPDATE"
    created_at: datetime

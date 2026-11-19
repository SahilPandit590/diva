"""
Entity, alias, attribute, and inter-memory relationship contracts for Diva Memory Engine v3.0.
"""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

from memory_engine.types.enums import (
    AliasType,
    DomainPartition,
    EntityStatus,
    EntityType,
    EpistemicType,
    MemoryRelationshipType,
)


class Entity(BaseModel):
    """
    Distinct real-world or conceptual entity recognized across memory records.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: UUID
    canonical_name: str
    entity_type: EntityType = EntityType.UNKNOWN
    domain_partition: DomainPartition = DomainPartition.COGNITIVE
    first_observed_at: datetime
    last_observed_at: datetime
    observation_count: int = 1
    status: EntityStatus = EntityStatus.ACTIVE


class EntityAlias(BaseModel):
    """
    Alternate identifier, nickname, or handle pointing to an entity.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    alias_id: UUID
    entity_id: UUID
    alias_text: str
    alias_type: AliasType = AliasType.NICKNAME
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_engine: str
    established_at: datetime


class EntityAttribute(BaseModel):
    """
    Temporal attribute asserted about an entity.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    attribute_id: UUID
    entity_id: UUID
    attribute_key: str
    attribute_value: str
    epistemic_type: EpistemicType
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    source_claim_id: UUID | None = None


class MemoryRelationship(BaseModel):
    """
    Typed graph edge between two experiences or representations.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    relationship_id: UUID
    source_memory_id: UUID
    target_memory_id: UUID
    relationship_type: MemoryRelationshipType
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    established_by: str
    established_at: datetime

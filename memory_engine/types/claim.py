"""
Claim and evidence Pydantic models for Diva Memory Engine v3.0.
All models are frozen (immutable) to guarantee epistemic provenance and integrity.
"""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

from memory_engine.types.enums import (
    ClaimLifecycle,
    ClaimRelationshipType,
    DomainPartition,
    EpistemicType,
    EvidenceRole,
    EvidenceStatus,
)


class MemoryClaim(BaseModel):
    """
    Atomic propositional unit of Diva's knowledge base.
    Status changes produce new claim_versions records; canonical claim is immutable.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: UUID
    subject_entity_id: UUID | None = None
    predicate: str
    object_value: str
    canonical_statement: str
    epistemic_type: EpistemicType
    evidence_status: EvidenceStatus = EvidenceStatus.UNVERIFIED
    lifecycle: ClaimLifecycle = ClaimLifecycle.ACTIVE
    domain_partition: DomainPartition = DomainPartition.COGNITIVE
    source_engine: str
    source_session_id: UUID
    source_experience_id: UUID | None = None
    world_time_start: datetime | None = None
    world_time_end: datetime | None = None
    diva_time_recorded: datetime
    provenance_hash: str
    version: int = 1


class ClaimAssessment(BaseModel):
    """
    Engine-specific assessment of a claim.
    Confidence belongs to an assessor, NOT the objective claim itself.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    assessment_id: UUID
    claim_id: UUID
    assessor_engine: str
    assessor_session: UUID
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    assessed_at: datetime
    assessment_method: str = "DETERMINISTIC_RULE"


class EvidenceReference(BaseModel):
    """
    Tracks provenance and evidential support/opposition for a claim.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: UUID
    claim_id: UUID
    source_memory_id: UUID | None = None
    source_claim_id: UUID | None = None
    relationship: EvidenceRole
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    added_at: datetime


class ClaimRelationship(BaseModel):
    """
    Explicit, typed graph edge between two claims in claim_relationships.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    relationship_id: UUID
    claim_id_source: UUID
    claim_id_target: UUID
    relationship_type: ClaimRelationshipType
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    established_by: str
    established_at: datetime
    supporting_evidence: tuple[UUID, ...] = ()


class ProposedClaim(BaseModel):
    """
    Candidate claim submitted by an engine during development.
    Does NOT carry a database UUID; Memory Governance assigns UUID on acceptance.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    subject_entity_id: UUID | None = None
    predicate: str
    object_value: str
    canonical_statement: str
    epistemic_type: EpistemicType
    source_engine: str
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    rationale: str = ""


class ProposedRelationship(BaseModel):
    """
    Candidate relationship between claims submitted during development.
    Does NOT carry database UUID; assigned by Memory Governance upon acceptance.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id_source: UUID
    claim_id_target: UUID
    relationship_type: ClaimRelationshipType
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    rationale: str = ""
